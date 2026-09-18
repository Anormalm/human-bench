import json

import pytest

from shuorenhua_bench import model_judge


def windows_lock():
    error = PermissionError('temporary file lock')
    error.winerror = 5
    return error


def test_atomic_json_preserves_old_file_during_transient_windows_lock(tmp_path, monkeypatch):
    path = tmp_path / 'ledger.json'
    path.write_text('{"previous": true}', encoding='utf-8')
    replace = model_judge.os.replace
    calls, pauses = [], []

    def locked_then_available(source, destination):
        calls.append(destination)
        assert json.loads(path.read_text()) == {'previous': True}
        assert json.loads(source.read_text(encoding='utf-8')) == {'updated': '中文'}
        if len(calls) <= 2:
            raise windows_lock()
        replace(source, destination)

    monkeypatch.setattr(model_judge.os, 'replace', locked_then_available)
    monkeypatch.setattr(model_judge.time, 'sleep', pauses.append)
    model_judge.atomic_json(path, {'updated': '中文'})
    assert json.loads(path.read_text(encoding='utf-8')) == {'updated': '中文'}
    assert len(calls) == 3 and pauses == [.02, .04]
    assert not path.with_suffix('.json.tmp').exists()


@pytest.mark.parametrize('windows', [True, False])
def test_atomic_json_raises_after_bounded_retries_without_losing_prior_file(tmp_path, monkeypatch, windows):
    path = tmp_path / 'ledger.json'
    path.write_text('{"previous": true}', encoding='utf-8')
    calls, pauses = [], []

    def denied(source, destination):
        calls.append(destination)
        raise windows_lock() if windows else PermissionError('permanent permissions')

    monkeypatch.setattr(model_judge.os, 'replace', denied)
    monkeypatch.setattr(model_judge.time, 'sleep', pauses.append)
    with pytest.raises(PermissionError):
        model_judge.atomic_json(path, {'updated': True})
    assert json.loads(path.read_text()) == {'previous': True}
    assert len(calls) == (8 if windows else 1)
    assert len(pauses) == (7 if windows else 0)
    assert sum(pauses) < 2
