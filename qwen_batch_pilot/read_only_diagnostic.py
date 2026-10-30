"""Read-only Kaggle identity/existence diagnostic; no response bodies printed."""
import contextlib
import io
import json
import os
import sys

DATASET = 'sumuji/qwen-batch-synthetic-20261031'
KERNEL = 'sumuji/qwen-batch-private-pilot-20261031'
CONTROL = 'sumuji/qwen25-7b-kaggle-smoke'
DATASET_SENTINEL = 'sumuji/qwen-missing-diag-20261031-9f4c61'
KERNEL_SENTINEL = 'sumuji/qwen-missing-diag-20261031-9f4c61'


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def get_dataset(api, ref):
    from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest
    request = ApiGetDatasetRequest()
    request.owner_slug, request.dataset_slug = ref.split('/')
    with api.build_kaggle_client() as client:
        return client.datasets.dataset_api_client.get_dataset(request)


def get_kernel(api, ref):
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    request = ApiGetKernelRequest()
    request.user_name, request.kernel_slug = ref.split('/')
    with api.build_kaggle_client() as client:
        return client.kernels.kernels_api_client.get_kernel(request)


def exception_summary(exc):
    # Class names are restricted to avoid leaking exception messages or URLs.
    known = {'HTTPError', 'ValueError', 'TypeError', 'Timeout', 'ConnectionError',
             'OSError', 'RuntimeError'}
    name = type(exc).__name__
    name = name if name in known else 'other'
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    return {'outcome': 'error', 'exception_class': name, 'http_status': status}


def direct(label, fn):
    try:
        result = quiet(fn)
        valid = result is not None
        print(json.dumps({'probe': label, 'outcome': 'returned' if valid else 'none'}), flush=True)
    except Exception as exc:
        print(json.dumps({'probe': label, **exception_summary(exc)}), flush=True)


def inspect_list(fetch, attr, target, control=None):
    token = None
    tokens = set()
    pages = 0
    n = 0
    private = 0
    found = False
    control_found = False
    while pages < 20:
        result = quiet(fetch, page_size=100, page_token=token)
        rows = getattr(result, attr, None)
        if not isinstance(rows, list) or any(r is None or not isinstance(getattr(r, 'ref', None), str) for r in rows):
            raise RuntimeError('Malformed list result')
        pages += 1
        n += len(rows)
        private += sum(getattr(row, 'is_private', None) is True for row in rows)
        found |= any(row.ref == target for row in rows)
        control_found |= control is not None and any(row.ref == control for row in rows)
        token = getattr(result, 'next_page_token', None)
        if not token:
            return {'pages': pages, 'count': n, 'private_count': private, 'target_found': found,
                    'control_found': control_found if control is not None else None, 'pagination_complete': True}
        if not isinstance(token, str) or token in tokens:
            raise RuntimeError('Malformed pagination')
        tokens.add(token)
    return {'pages': pages, 'count': n, 'private_count': private, 'target_found': found,
            'control_found': control_found if control is not None else None, 'pagination_complete': False}


def listing(label, fn, attr, target, control=None):
    try:
        print(json.dumps({'probe': label, 'outcome': 'returned', **inspect_list(fn, attr, target, control)}), flush=True)
    except Exception as exc:
        print(json.dumps({'probe': label, **exception_summary(exc)}), flush=True)


def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise RuntimeError('Credential unavailable')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    quiet(api.authenticate)
    direct('existing_kernel_control', lambda: get_kernel(api, CONTROL))
    direct('target_dataset', lambda: get_dataset(api, DATASET))
    direct('dataset_sentinel', lambda: get_dataset(api, DATASET_SENTINEL))
    direct('target_kernel', lambda: get_kernel(api, KERNEL))
    direct('kernel_sentinel', lambda: get_kernel(api, KERNEL_SENTINEL))
    listing('my_dataset_list', lambda **kw: api.dataset_list_with_response(mine=True, **kw), 'datasets', DATASET)
    listing('my_kernel_list', lambda **kw: api.kernels_list_with_response(mine=True, **kw), 'kernels', KERNEL, CONTROL)
    print('Read-only diagnostic completed; no object was created or modified.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'probe': 'setup', **exception_summary(exc)}), file=sys.stderr)
        sys.exit(1)
