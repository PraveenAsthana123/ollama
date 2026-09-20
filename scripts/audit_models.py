"""Bounded, sequential local Ollama smoke checks; no model downloads/deletions."""
import argparse
import json
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('model-checks.jsonl'))
    parser.add_argument('--max-model-gb', type=float, default=6.1)
    args = parser.parse_args()
    session = requests.Session()
    session.trust_env = False
    models = session.get(args.base_url + '/api/tags', timeout=10).json()['models']
    already = set()
    if args.output.exists():
        already = {json.loads(line)['model'] for line in args.output.read_text().splitlines()}
    for index, model in enumerate(sorted(models, key=lambda m: m['size']), 1):
        name = model['name']
        if name in already:
            continue
        result = {'model': name, 'size_gb': round(model['size'] / 1e9, 3),
                  'capabilities': model.get('capabilities', []), 'timestamp': time.time()}
        if model['size'] > args.max_model_gb * 1e9:
            result.update(status='not_load_tested', reason='Exceeds conservative GPU-fit threshold; retained for explicit large-model use.')
        else:
            started = time.monotonic()
            try:
                if 'embedding' in result['capabilities']:
                    response = session.post(args.base_url + '/api/embed', json={
                        'model': name, 'input': 'Local model health check.',
                        'keep_alive': '1m', 'options': {'num_ctx': 2048}}, timeout=(5, 90))
                else:
                    payload = {'model': name, 'prompt': 'Write one short greeting.',
                               'stream': False, 'keep_alive': '1m',
                               'options': {'num_ctx': 2048, 'num_predict': 8, 'temperature': 0}}
                    if 'thinking' in result['capabilities'] and not name.startswith('deepseek-r1'):
                        payload['think'] = False
                    response = session.post(args.base_url + '/api/generate', json=payload, timeout=(5, 90))
                data = response.json()
                if not response.ok or data.get('error'):
                    raise RuntimeError(str(data.get('error', response.status_code)))
                loaded = session.get(args.base_url + '/api/ps', timeout=5).json()['models']
                current = next((m for m in loaded if m['name'] == name), {})
                result.update(status='passed', wall_seconds=round(time.monotonic() - started, 3),
                              load_seconds=round(data.get('load_duration', 0) / 1e9, 3),
                              gpu_bytes=current.get('size_vram', 0), loaded_bytes=current.get('size', 0))
                if 'embeddings' in data:
                    assert data['embeddings'] and data['embeddings'][0]
                    result['embedding_dimensions'] = len(data['embeddings'][0])
                else:
                    assert data.get('response') or data.get('thinking'), 'No generated text'
                    result['output_sample'] = data.get('response', '')[:120]
                    result['generated_tokens'] = data.get('eval_count', 0)
                    result['tokens_per_second'] = round(data.get('eval_count', 0) / max(data.get('eval_duration', 0) / 1e9, .001), 2)
            except Exception as error:
                result.update(status='failed', error=str(error)[:800], wall_seconds=round(time.monotonic() - started, 3))
            finally:
                # Release only the model loaded by this check, not other users' models.
                try:
                    session.post(args.base_url + '/api/generate', json={'model': name, 'keep_alive': 0}, timeout=(3, 10))
                except requests.RequestException:
                    pass
        with args.output.open('a') as output:
            output.write(json.dumps(result) + '\n')
        print(f"[{index}/{len(models)}] {name}: {result['status']} "
              f"{result.get('tokens_per_second', '')} tok/s {result.get('error', '')[:120]}", flush=True)


if __name__ == '__main__':
    main()
