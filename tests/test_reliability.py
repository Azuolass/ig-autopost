import json
from datetime import date, datetime, timezone
from unittest.mock import Mock

import pytest

from autopost import comments, drive, prepare, publish, queue
from autopost.instagram import Instagram, InstagramError


def test_late_post_is_persistently_skipped(tmp_path, monkeypatch):
    path = tmp_path / 'queue.json'
    path.write_text(json.dumps([{'date': '2000-01-01', 'slot': 1, 'at': '2000-01-01 15:00'}]))
    monkeypatch.setattr(queue, 'QUEUE', path)
    monkeypatch.setattr(publish, 'STATE_FILE', tmp_path / 'published.json')
    notify = Mock()
    monkeypatch.setattr(publish, 'notify', notify)
    monkeypatch.setattr(publish, 'main', Mock(side_effect=AssertionError('must not publish')))
    queue.main()
    assert json.loads(path.read_text())[0]['skip'] is True
    queue.main()
    assert notify.call_count == 1


def test_preview_uses_queue_exception_and_no_old_schedule(tmp_path, monkeypatch):
    (tmp_path / 'trigger').mkdir()
    path = tmp_path / 'trigger/queue.json'
    path.write_text(json.dumps([
        {'date': '2026-10-25', 'slot': 3, 'at': '2026-10-25 21:00'},
        {'date': '2026-10-26', 'slot': 3, 'at': '2026-10-26 23:00'},
        {'date': '2026-10-26', 'slot': 2, 'at': '2026-10-26 19:00', 'skip': True}]))
    monkeypatch.setattr(prepare, 'ROOT', tmp_path)
    assert prepare.vilnius_time(date(2026, 10, 25), 3) == '2026-10-25 21:00'
    assert prepare.vilnius_time(date(2026, 10, 26), 3) == '2026-10-26 23:00'
    assert prepare.vilnius_time(date(2026, 10, 26), 2) is None
    assert prepare.vilnius_time(date(2026, 10, 29), 1) is None


def test_secret_folder_overrides_config_and_publish_uses_it(monkeypatch):
    monkeypatch.setenv('DRIVE_ROOT_FOLDER_ID', 'SECRET_ROOT')
    fake = Mock()
    fake.list_children.return_value = []
    monkeypatch.setattr(drive, 'Drive', lambda: fake)
    with pytest.raises(RuntimeError, match='no month folder'):
        publish.fetch_post(date(2026, 10, 26), 1)
    fake.list_children.assert_called_once_with('SECRET_ROOT')


def test_edge_reads_all_pages_dedupes_and_never_follows_next_url():
    ig = Instagram('secret', 'me', 'https://graph.instagram.com/v23.0')
    ig._call = Mock(side_effect=[
        {'data': [{'id': '1'}], 'paging': {'next': 'https://untrusted.example/?access_token=secret',
                                         'cursors': {'after': 'opaque'}}},
        {'data': [{'id': '1'}, {'id': '2'}]}])
    assert list(ig.edge('post/comments', limit=50)) == [{'id': '1'}, {'id': '2'}]
    assert ig._call.call_args_list[1].args == ('GET', 'post/comments')
    assert ig._call.call_args_list[1].kwargs['after'] == 'opaque'


def test_edge_stops_at_configured_post_count_and_detects_bad_cursor():
    ig = Instagram('t', 'me', 'https://graph.instagram.com')
    page = {'data': [{'id': '1'}, {'id': '2'}],
            'paging': {'next': 'next', 'cursors': {'after': 'same'}}}
    ig._call = Mock(return_value=page)
    assert len(list(ig.edge('me/media', max_items=1))) == 1
    assert ig._call.call_count == 1
    with pytest.raises(InstagramError, match='repeated'):
        list(ig.edge('me/media'))


@pytest.fixture
def comment_env(tmp_path, monkeypatch):
    monkeypatch.setenv('IG_ACCESS_TOKEN', 'fake')
    monkeypatch.setattr(comments, 'STATE_FILE', tmp_path / 'comments.json')
    monkeypatch.setattr(comments.time, 'sleep', lambda _: None)
    notes = []
    monkeypatch.setattr(comments, 'notify', notes.append)
    storage = {'initialized': True, 'seen': {}}
    comments.STATE_FILE.write_text(json.dumps(storage))
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')

    class FakeIG(Instagram):
        fail = False
        existing_reply = False
        sent = []
        pages = []

        def me(self):
            return {'user_id': 'me', 'username': 'successhunters.prints'}

        def _call(self, method, path, **params):
            self.pages.append((method, path, params.get('after')))
            if path == 'me/media':
                return {'data': [{'id': 'post', 'permalink': 'https://instagram.com/p/test'}]}
            if path == 'post/comments':
                if params.get('after'):
                    return {'data': [{'id': 'target', 'text': 'price?', 'username': 'buyer',
                                      'timestamp': stamp, 'replies': {'data': []}}]}
                return {'data': [{'id': f'old{i}', 'text': 'x', 'timestamp': stamp} for i in range(50)],
                        'paging': {'next': 'next', 'cursors': {'after': 'second'}}}
            if path == 'target/replies' and method == 'GET':
                return {'data': [{'id': 'reply', 'username': 'successhunters.prints'}]
                        if self.existing_reply else []}
            if method == 'POST':
                self.sent.append(path)
                if self.fail:
                    raise InstagramError('temporary failure', 2)
                return {'id': 'new_reply'}
            raise AssertionError((method, path))

    # Existing comments are not re-answered; the new target is on page two.
    storage['seen'] = {f'old{i}': {'ts': stamp, 'action': 'baseline'} for i in range(50)}
    comments.STATE_FILE.write_text(json.dumps(storage))
    fake = FakeIG('t', 'me', 'https://graph.instagram.com')
    monkeypatch.setattr(comments, 'Instagram', lambda *args: fake)
    return fake, notes


def test_comment_after_first_50_is_answered_once(comment_env):
    ig, notes = comment_env
    comments.main([])
    comments.main([])
    assert ig.sent == ['target/replies']
    assert ('GET', 'post/comments', 'second') in ig.pages


def test_failure_retries_with_backoff_then_success(comment_env):
    ig, notes = comment_env
    ig.fail = True
    comments.main([])
    state = json.loads(comments.STATE_FILE.read_text())
    assert state['seen']['target']['attempts'] == 1
    assert 'atsakyti nepavyko' in notes[-1]
    comments.main([])
    assert len(ig.sent) == 1  # backoff has not elapsed
    state['seen']['target']['retry_after'] = ''
    comments.STATE_FILE.write_text(json.dumps(state))
    ig.fail = False
    comments.main([])
    assert len(ig.sent) == 2
    comments.main([])
    assert len(ig.sent) == 2


def test_retry_checks_for_existing_reply_before_sending(comment_env):
    ig, _ = comment_env
    state = json.loads(comments.STATE_FILE.read_text())
    state['seen']['target'] = {'ts': datetime.now(timezone.utc).isoformat(),
                               'action': 'reply failed: legacy failure'}
    comments.STATE_FILE.write_text(json.dumps(state))
    ig.existing_reply = True
    comments.main([])
    assert not ig.sent
    assert json.loads(comments.STATE_FILE.read_text())['seen']['target']['action'] == 'already answered'


def test_retries_stop_after_three_attempts(comment_env):
    ig, _ = comment_env
    ig.fail = True
    for _ in range(4):
        comments.main([])
        state = json.loads(comments.STATE_FILE.read_text())
        state['seen']['target']['retry_after'] = ''
        comments.STATE_FILE.write_text(json.dumps(state))
    assert len(ig.sent) == 3
