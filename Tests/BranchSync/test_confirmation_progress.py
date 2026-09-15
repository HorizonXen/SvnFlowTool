"""Compile the real review action model; no app UI or SVN writes."""
import pathlib
import subprocess
import tempfile
import unittest

class ConfirmationProgressTests(unittest.TestCase):
    def test_progress_lifecycle(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        model = (root / 'Sources/SvnFlow/ComparisonReview.swift').read_text().split('struct ComparisonReviewBar: View')[0]
        code = model + r'''
@MainActor final class SyncProgressModel {}
@main struct Checks {
    @MainActor static func main() async {
        var writes = 0, next = 0
        var gate: CheckedContinuation<Void, Never>?
        let action = ComparisonReviewActions(title: "test", summary: "", accept: {
            writes += 1
            await withCheckedContinuation { gate = $0 }
        }, skip: {}, next: { next += 1 }, pause: {})
        action.resultSummary = { "内容已一致，未重复写入" }
        let task = Task { await action.decide(true) }
        while gate == nil { await Task.yield() }
        assert(action.busy && action.showsWriteProgress)
        action.finishWritePresentation()
        assert(action.showsWriteProgress)
        await action.decide(true)
        assert(writes == 1 && next == 0)
        gate!.resume(); await task.value
        assert(!action.busy && action.resolved && action.showsWriteProgress)
        assert(action.writeResult == "内容已一致，未重复写入" && next == 0)
        action.finishWritePresentation(); action.writePresentationDidDismiss()
        assert(!action.showsWriteProgress && next == 1)
        let failure = ComparisonReviewActions(title: "test", summary: "", accept: {
            throw NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "核验失败"])
        }, skip: {}, next: { next += 1 }, pause: {})
        await failure.decide(true)
        assert(failure.showsWriteProgress && !failure.busy && !failure.resolved && failure.error == "核验失败")
        failure.finishWritePresentation(); failure.writePresentationDidDismiss()
        assert(next == 1)
        let skip = ComparisonReviewActions(title: "test", summary: "", accept: {}, skip: {}, next: { next += 1 }, pause: {})
        await skip.decide(false)
        assert(!skip.showsWriteProgress && skip.resolved && next == 2)
        print("confirmation progress lifecycle passed")
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'Checks.swift'
            binary = pathlib.Path(directory) / 'checks'
            source.write_text(code)
            subprocess.run(['swiftc', '-parse-as-library', str(source), '-o', str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, timeout=20)

if __name__ == '__main__':
    unittest.main()
