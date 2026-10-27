"""Migration retains edits; standard editor round trips keep dataset identities."""
from argparse import Namespace
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from north16.annotations.management import organize, plan, inventory, refresh
from north16.common.files import sha256, read_table
from test_dataset_workspace import fixture


class ManagementTests(unittest.TestCase):
    def test_legacy_archive_preserves_bytes_and_unknown_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root)
            base=root/'annotations';legacy=base/'xanylabeling_20260902_044232'
            (legacy/'visible/back_04').mkdir(parents=True)
            edit=legacy/'visible/back_04/f000000.json';edit.write_text('{"human_edit":true}',encoding='utf-8')
            (base/'custom').mkdir()
            before=sha256(edit);original=sha256(root/'samples.txt')
            proposed=plan(root)
            self.assertEqual(proposed['unknown_directories'],['custom'])
            self.assertTrue(legacy.exists());self.assertFalse((base/'archive').exists())
            report=organize(root)
            self.assertEqual(report['status'],'succeeded')
            self.assertEqual(sha256(base/'archive/xanylabeling_20260902_044232/visible/back_04/f000000.json'),before)
            self.assertFalse(legacy.exists());self.assertTrue((base/'custom').exists())
            self.assertEqual(sha256(root/'samples.txt'),original)
            self.assertEqual(inventory(root)[0]['kind'],'archive')
            self.assertFalse(plan(root)['moves'])
            self.assertTrue((base/'README.txt').exists())

    def test_conflict_fails_before_move_and_verification_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root)
            base=root/'annotations';legacy=base/'grabcut_camera04';legacy.mkdir(parents=True)
            (legacy/'note.txt').write_text('preserve',encoding='utf-8')
            (base/'archive/grabcut_camera04').mkdir(parents=True)
            with self.assertRaises(ValueError):organize(root)
            self.assertTrue(legacy.exists())
            (base/'archive/grabcut_camera04').rmdir()
            from north16.annotations.management import tree_identity
            actual=tree_identity(legacy)
            with patch('north16.annotations.management.tree_identity',side_effect=[actual,{}]):
                with self.assertRaises(ValueError):organize(root)
            self.assertEqual((legacy/'note.txt').read_text(encoding='utf-8'),'preserve')
            self.assertFalse((base/'archive/grabcut_camera04').exists())

    def test_default_corrected_output_and_export_cli_for_new_drafts(self):
        from north16.annotations.dataset_workspace import DatasetWorkspace,run_dataset_job
        from north16.annotations.profiles import DEFAULT_PROFILE
        from north16.annotations.xanylabeling import export_project,import_project
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'datasets';fixture(root)
            ws=DatasetWorkspace(root);key=ws.keys()[0]
            originals={p:sha256(p) for p in root.rglob('*') if p.is_file()}
            profile=deepcopy(DEFAULT_PROFILE);profile['working_wh']=[256,144]
            draft=ws.output_path('drafts',key,'batch_a')
            run_dataset_job(ws,key,ws.images(key)[:1],profile,draft)
            project=ws.output_path('projects',key,draft.name)
            export_project(Namespace(root=str(root),draft=str(draft),output=str(project),camera=None,limit=None))
            edit=project/'images/f000000.json'
            data=json.loads(edit.read_text(encoding='utf-8'))
            data['shapes'].append(dict(label='other',shape_type='polygon',points=[[2,2],[8,2],[8,8],[2,8]]))
            edit.write_text(json.dumps(data),encoding='utf-8');edited_sha=sha256(edit)
            import_project(Namespace(project=str(project),output=None,changed_only=True,preview=True))
            corrected=list((root/'annotations/corrected'/key[0]/key[1]/key[2]).iterdir())
            self.assertEqual(len(corrected),1)
            self.assertTrue((corrected[0]/'masks/f000000.png').exists())
            row=read_table(corrected[0]/'samples.txt')[0]
            self.assertEqual(row['id'],ws.streams[key][0]['id'])
            self.assertEqual(row['label_status'],'draft')
            self.assertTrue((root/row['mask']).is_file())
            self.assertEqual(sha256(edit),edited_sha)
            for p,digest in originals.items():self.assertEqual(sha256(p),digest)
            self.assertEqual({row['kind'] for row in read_table(root/'annotations/index.txt')},{'drafts','projects','corrected'})
            # A fresh unchanged export can be imported with zero changed frames.
            second=ws.output_path('projects',key,'batch_b');export_project(Namespace(root=str(root),draft=str(draft),output=str(second),camera=None,limit=None))
            import_project(Namespace(project=str(second),output=None,changed_only=True,preview=False))
            self.assertEqual(len(inventory(root)),5)


if __name__=='__main__':unittest.main()
