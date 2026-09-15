import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from galaxy_sync import merge,parse

def asset(*items,tail='  releaseOnly: keep\n'):
 return ('%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!114 &11400000\nMonoBehaviour:\n  interactionObjs:\n'+''.join('  - name: obj\n    id: '+str(i)+'\n    position: {x: '+str(x)+', y: '+str(y)+', z: 0}\n    resourceId: '+r+'\n' for i,x,y,r in items)+tail).encode()

class MethodTest(unittest.TestCase):
 def test_id_alignment_and_preserve_unrelated_components(self):
  a=asset((1,0,0,'a'),(2,0,0,'b'));b=asset((2,0,0,'b'),(1,10,0,'a'));t=asset((2,0,0,'release'),(1,0,99,'a'),(3,8,8,'extra'))
  got=merge(a,b,t,True);self.assertEqual(got,asset((2,0,0,'release'),(1,10,99,'a'),(3,8,8,'extra')))
 def test_added_deleted_and_reversion(self):
  a=asset((1,0,0,'a'),(2,0,0,'b'));b=asset((1,10,0,'a'),(3,0,0,'c'));t=asset((1,0,5,'a'),(2,0,0,'b'),(4,0,0,'extra'))
  got=merge(a,b,t,True);self.assertEqual(got,asset((1,10,5,'a'),(4,0,0,'extra'),(3,0,0,'c')))
  reverted=merge(b,asset((1,0,0,'a'),(3,0,0,'c')),got,True);self.assertEqual(parse(reverted)[2]['1'][1]['position'].strip(),'{x: 0, y: 5, z: 0}')
 def test_duplicate_id(self):
  a=asset((1,0,0,'a'));self.assertRaisesRegex(ValueError,'重复 ID',merge,a,a,asset((1,0,0,'a'),(1,1,1,'b')),True)
 def test_missing_changed_id(self):
  self.assertRaisesRegex(ValueError,'缺少作者修改',merge,asset((1,0,0,'a')),asset((1,1,0,'a')),asset((2,0,0,'b')),True)
 def test_added_id_collision(self):
  self.assertRaisesRegex(ValueError,'已被 Release 占用',merge,asset((1,0,0,'a')),asset((1,0,0,'a'),(2,0,0,'b')),asset((1,0,0,'a'),(2,1,0,'b')),True)
 def test_authored_addition_existing_same_identity(self):
  def identified(data):return data.replace(b'    position:',b'    interactiveId: 999\n    objectType: 8\n    position:')
  a=identified(asset((1,0,0,'a')));b=identified(asset((1,0,0,'a'),(2,1,0,'b')));t=identified(asset((1,0,0,'a'),(2,99,0,'b')))
  self.assertEqual(merge(a,b,t,True),b)
  self.assertRaisesRegex(ValueError,'已被 Release 占用',merge,a,b,t.replace(b'interactiveId: 999',b'interactiveId: 888'),True)
 def test_unchanged_fields_keep_exact_bytes(self):
  a=asset((1,0,0,'a'));b=asset((1,1,0,'a'));t=asset((1,0,0,'a')).replace(b'x: 0, y: 0',b'x: 0.000, y: 0.000')
  got=merge(a,b,t,True);self.assertIn(b'x: 1, y: 0.000',got)
 def test_tool_routes_galaxy_asset_through_ids(self):
  from file_sync import merge_data
  a=asset((1,0,0,'a'),(2,0,0,'b'));b=asset((1,10,0,'a'),(2,0,0,'b'));t=asset((2,0,0,'release'),(1,0,99,'a'))
  self.assertEqual(merge_data(a,b,t,'Client/Assets/Arts/SeasonRes2/Config/Galaxy/StarProvince/s2galaxy/52101.asset',True),asset((2,0,0,'release'),(1,10,99,'a')))
 def test_duplicate_id_is_rejected_even_when_release_equals_base(self):
  from file_sync import merge_data
  a=asset((1,0,0,'a'));b=asset((1,0,0,'a'),(1,1,0,'b'))
  self.assertRaisesRegex(ValueError,'重复 ID',merge_data,a,b,a,'Client/Assets/Arts/SeasonRes2/Config/Galaxy/52101.asset',True)
 def test_old_galaxy_candidate_is_rejected_before_write(self):
  import staged_sync
  path='Client/Assets/Arts/SeasonRes2/Config/Galaxy/52101.asset'
  state={'items':{path:{'status':'ready','authorIsolation':8}}}
  self.assertRaisesRegex(RuntimeError,'星系对象合并规则已更新',staged_sync.accept,None,Path('.'),{'config':{}},state,path)
 def test_outside_source_change_stops(self):
  self.assertRaisesRegex(ValueError,'以外内容',merge,asset((1,0,0,'a')),asset((1,1,0,'a'),tail='  releaseOnly: changed\n'),asset((1,0,0,'a')),True)
 def test_strict_conflict(self):
  self.assertRaisesRegex(ValueError,'字段冲突',merge,asset((1,0,0,'a')),asset((1,1,0,'a')),asset((1,2,0,'a')),False)
if __name__=='__main__':unittest.main()
