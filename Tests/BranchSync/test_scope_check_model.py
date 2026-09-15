"""Exercise selection results and invalidation using the real Swift draft."""
import pathlib
import subprocess
import tempfile
import unittest

class ScopeCheckModelTests(unittest.TestCase):
    def test_results_and_invalidation(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        source = (root/'Sources/SvnFlow/BranchSyncWindow.swift').read_text().split('struct SyncWithdrawnRow:')[0]
        source += (root/'Sources/SvnFlow/SyncProgressView.swift').read_text().split('struct SyncActivity:')[0]
        source += (root/'Sources/SvnFlow/SyncScopeDraft.swift').read_text()
        source = source.replace('UserDefaults.standard', 'testDefaults')
        source += r'''
let testDefaults = UserDefaults(suiteName: "scope-check-test-" + UUID().uuidString)!
@main struct Checks {
 @MainActor static func main() throws {
  let draft = SyncScopeDraft()
  draft.setup(author: "a", days: 30)
  let data = Data(#"{"config":{"dev":"dev","release":"release","target":"target","author":"a","days":30,"start":"0","end":"9","snapshot":10},"dev":[{"revision":5,"date":"today","message":"change","paths":[]}],"fileItems":[{"path":"a.txt","kind":"file","revisions":[5],"latestRevision":5,"message":"","date":""},{"path":"b.txt","kind":"file","revisions":[5],"latestRevision":5,"message":"","date":""}]}"#.utf8)
  draft.preview = try JSONDecoder().decode(SyncReport.self, from:data)
  draft.selectedRevisions = [5]
  let result = RemainingDiffResult(snapshot: 10, noDiffPaths: ["a.txt","b.txt"], differentPaths: [], errors: [:], localStates: ["a.txt":"same","b.txt":"different"], complete: true)
  draft.checkResult = result
  assert(draft.mergedPaths == ["a.txt"] && draft.remainingCount == 1)
  draft.directories = ["other"]
  assert(draft.checkResult == nil)
  draft.checkResult = result; draft.selectedRevisions = []
  assert(draft.checkResult == nil && draft.selectedCount == 0)
  draft.checkResult = result; draft.checking = true; draft.invalidateCheck()
  assert(!draft.checking && draft.checkResult == nil)
  draft.selectedRevisions = [5]; draft.checkResult = result; draft.cancelRead()
  assert(draft.checkResult == nil && draft.selectedRevisions == [5])
 }
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            folder=pathlib.Path(tmp)
            (folder/'main.swift').write_text(source)
            objects=list((root/'.build/release/SVNCore.build').glob('*.swift.o'))
            subprocess.run(['swiftc','-parse-as-library','-I',str(root/'.build/release/Modules'),str(folder/'main.swift'),*map(str,objects),'-o',str(folder/'checks')],check=True,capture_output=True,text=True)
            subprocess.run([str(folder/'checks')],check=True,capture_output=True,text=True)
