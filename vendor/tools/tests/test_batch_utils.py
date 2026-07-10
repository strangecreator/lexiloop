import json

import pytest

from tools.batch_utils import run_batch_aiohttp


@pytest.mark.asyncio
async def test_skipped_errors_can_be_saved_as_structured_jsonl(tmp_path):
    async def run_single(*, value, session, timeout):
        if value == 'bad':
            raise TimeoutError('Gateway timed out')
        return {'content': value, 'stats': {'total_price': 0}}

    output = tmp_path / 'results.jsonl'
    result = await run_batch_aiohttp(
        run_single,
        [{'value': 'ok'}, {'value': 'bad'}],
        batch_size=2,
        save_to_file=str(output),
        override=True,
        only_new=True,
        skip_on_error=True,
        save_errors_to_file=True,
        verbose=False,
    )

    assert result['count'] == 1
    lines = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
    assert lines[0]['index'] == 0
    assert lines[0]['content'] == 'ok'
    assert lines[1]['index'] == 1
    assert lines[1]['__error_type__'] == 'TimeoutError'
    assert 'Gateway timed out' in lines[1]['__error__']
