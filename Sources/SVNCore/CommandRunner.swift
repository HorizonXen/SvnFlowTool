import Foundation

/// Keeps diagnostic output separate so warnings cannot corrupt XML responses.
public struct CommandResult: Sendable {
    public let standardOutput: Data
    public let standardError: Data
    public let exitCode: Int32

    public var outputText: String { String(decoding: standardOutput, as: UTF8.self) }
    public var errorText: String { String(decoding: standardError, as: UTF8.self) }
    public var displayText: String {
        [outputText, errorText]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }.joined(separator: "\n")
    }

    public func checked() throws -> CommandResult {
        guard exitCode == 0 else { throw CommandFailure(result: self) }
        return self
    }
}

public struct CommandFailure: LocalizedError, Sendable {
    public let result: CommandResult
    public var errorDescription: String? {
        let diagnostic = result.errorText.trimmingCharacters(in: .whitespacesAndNewlines)
        let message = diagnostic.isEmpty ? result.outputText.trimmingCharacters(in: .whitespacesAndNewlines) : diagnostic
        return message.isEmpty ? "命令执行失败（退出码 \(result.exitCode)）" : String(message.prefix(12_000))
    }
}

// Each pipe has exactly one reader. Access to its completed data is synchronized.
private final class PipeCapture: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func read(_ handle: FileHandle, onData: (@Sendable (Data) -> Void)? = nil) {
        var captured = Data()
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { break }
            captured.append(chunk)
            onData?(chunk)
        }
        lock.lock()
        data = captured
        lock.unlock()
    }

    func value() -> Data {
        lock.lock()
        defer { lock.unlock() }
        return data
    }
}

public struct CommandRunner: Sendable {
    public init() {}

    /// Blocking API: call outside the main actor. Both pipes are drained concurrently.
    public func run(executable: URL, arguments: [String], directory: URL? = nil, environment: [String: String]? = nil, onOutput: (@Sendable (Data) -> Void)? = nil) throws -> CommandResult {
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        // GUI launches can inherit ASCII CTYPE with translated SVN messages.
        // Keep command output UTF-8 and diagnostic language deterministic,
        // independently of the app's interface language.
        var childEnvironment = environment ?? ProcessInfo.processInfo.environment
        for name in ["LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES"] { childEnvironment[name] = "en_US.UTF-8" }
        childEnvironment["LANGUAGE"] = "en"
        if executable.lastPathComponent.hasPrefix("python") {
            childEnvironment["PYTHONDONTWRITEBYTECODE"] = "1"
        }
        process.environment = childEnvironment
        process.currentDirectoryURL = directory
        process.standardInput = FileHandle.nullDevice
        let output = Pipe()
        let error = Pipe()
        process.standardOutput = output
        process.standardError = error
        try process.run()

        let readers = DispatchGroup()
        let capturedOutput = PipeCapture()
        let capturedError = PipeCapture()
        DispatchQueue.global(qos: .userInitiated).async(group: readers) {
            capturedOutput.read(output.fileHandleForReading, onData: onOutput)
        }
        DispatchQueue.global(qos: .userInitiated).async(group: readers) {
            capturedError.read(error.fileHandleForReading)
        }
        process.waitUntilExit()
        readers.wait()
        return CommandResult(standardOutput: capturedOutput.value(), standardError: capturedError.value(), exitCode: process.terminationStatus)
    }
}
