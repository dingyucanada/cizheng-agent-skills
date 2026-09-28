from cizheng.demo import import_demo
from cizheng.store import Store


def test_public_demo_has_no_fake_assessment_and_import_is_idempotent(tmp_path):
    result=import_demo(tmp_path);again=import_demo(tmp_path)
    assert result==again and result['model_calls']==0 and result['assessment'] is None
    assert result['media_count']==2
    store=Store(tmp_path);assert store.listing('run')==[]
    assert '非盲测' in store.read('case',result['case_id'])['source_declaration']


def test_readable_export_includes_real_image_and_escaped_content(tmp_path):
    from cizheng.api import export_bundle
    from cizheng.reporting import markdown_report, html_report
    from test_closed_loop import create_case, add_photo, run_case
    store=Store(tmp_path);case=add_photo(store,create_case(store));run=run_case(store,case)
    case=store.read('case',case['id']);case['title']='<script>bad()</script>'
    bundle=export_bundle(store,case,run);md=markdown_report(bundle);document=html_report(bundle,store.blob)
    assert '制作时期' in md and '下一项优先补证' in md
    assert '<script>bad' not in document and '&lt;script&gt;' in document
    assert 'data:image/jpeg;base64,' in document and '原图SHA256' in document
