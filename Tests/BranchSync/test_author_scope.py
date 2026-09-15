import datetime as dt
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
import branch_sync

class AuthorScopeTests(unittest.TestCase):
    def test_exact_window_deduplicates_and_excludes_svn_lower_boundary(self):
        tree=ET.fromstring('''<log>
          <logentry><author>before</author><date>2026-08-10T11:59:59.999999Z</date></logentry>
          <logentry><author>start</author><date>2026-08-10T12:00:00Z</date></logentry>
          <logentry><author>middle</author><date>2026-09-01T00:00:00Z</date></logentry>
          <logentry><author>middle</author><date>2026-09-01T01:00:00Z</date></logentry>
          <logentry><author>end</author><date>2026-09-09T12:00:00Z</date></logentry>
          <logentry><author>future</author><date>2026-09-09T12:00:00.000001Z</date></logentry>
          <logentry><author>malformed</author><date>bad</date></logentry>
          <logentry><author>undated</author></logentry>
        </log>''')
        start=dt.datetime(2026,8,10,12,tzinfo=dt.timezone.utc)
        self.assertEqual(branch_sync.authors_in_range(tree,start,start+dt.timedelta(days=30)),['end','middle','start'])

    def test_no_commits_returns_empty_list(self):
        now=dt.datetime.now(dt.timezone.utc)
        self.assertEqual(branch_sync.authors_in_range(ET.fromstring('<log/>'),now-dt.timedelta(days=1),now),[])
