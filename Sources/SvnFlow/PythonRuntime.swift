import Foundation

enum PythonRuntime {
    struct Invocation {
        let executable: URL
        let arguments: [String]
    }

    static func invocation(resources: URL, arguments: [String]) throws -> Invocation {
        let packaged = resources.appendingPathComponent("svnflow-python")
        if FileManager.default.isExecutableFile(atPath: packaged.path) {
            return Invocation(executable: packaged, arguments: arguments)
        }
        let candidates = [
            resources.appendingPathComponent("python/bin/python3.12").path,
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        guard let path = candidates.first(where: FileManager.default.isExecutableFile(atPath:)) else {
            throw NSError(
                domain: "SvnFlow.PythonRuntime",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "缺少合入运行环境"]
            )
        }
        return Invocation(executable: URL(fileURLWithPath: path), arguments: arguments)
    }
}
