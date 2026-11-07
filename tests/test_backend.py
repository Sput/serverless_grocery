import copy
import json
import os
import sys
import uuid
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts'), str(ROOT / 'prototypes')]
import app
import public_meals
from app import ApiError, DynamoRepository, HOUSEHOLD, Service, record_key, visible
from migrate import normalize, apply


@pytest.fixture
def repo(monkeypatch):
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    with mock_aws():
        client = boto3.client('dynamodb', region_name='us-east-1')
        client.create_table(TableName='groceries-test', BillingMode='PAY_PER_REQUEST',
            KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'pk', 'AttributeType': 'S'}, {'AttributeName': 'sk', 'AttributeType': 'S'}])
        repository = DynamoRepository('groceries-test')
        client.put_item(TableName=repository.table, Item=repository.pack({
            'pk': HOUSEHOLD, 'sk': 'META', 'revision': 0, 'clearThrough': -1, 'migrationState': 'ready'}))
        yield repository


def mutate(service, path, body, method='POST', key=None):
    return service.mutate(method, path, body, key or str(uuid.uuid4()))


def seed(repo, kind, identifier='one', **fields):
    row = {'pk': HOUSEHOLD, 'sk': record_key(kind, identifier), 'id': identifier, 'kind': kind,
           'version': 1, 'createdRevision': 0, **fields}
    repo.client.put_item(TableName=repo.table, Item=repo.pack(row))
    return row


def test_inventory_and_locations(repo):
    service = Service(repo)
    mutate(service, '/locations', {'location': 'Pantry'})
    with pytest.raises(ApiError, match='already exists'):
        mutate(service, '/locations', {'location': 'Pantry'})
    mutate(service, '/items', {'name': ' Rice ', 'location': 'Pantry'})
    row = service.get('/items')['items'][0]
    assert row['name'] == 'Rice' and row['zone'] is None
    mutate(service, f'/items/{row["id"]}', {'location': 'Pantry', 'version': 1}, 'PATCH')
    with pytest.raises(ApiError, match='Record changed'):
        mutate(service, f'/items/{row["id"]}', {'location': 'Pantry', 'version': 1}, 'PATCH')
    with pytest.raises(ApiError, match='existing location'):
        mutate(service, '/items', {'name': 'Eggs', 'location': 'Unknown'})


def test_append_and_safe_retry(repo):
    seed(repo, 'items', name='Eggs', location='Fridge', zone=3)
    service = Service(repo)
    body = {'entries': [{'kind': 'items', 'id': 'one', 'store': 'costco'}]}
    key = str(uuid.uuid4())
    first = mutate(service, '/shopping/selections', body, key=key)
    assert mutate(service, '/shopping/selections', body, key=key) == first
    assert len(service.get('/shopping')['costco']) == 1
    mutate(service, '/shopping/selections', body)
    assert len(service.get('/shopping')['costco']) == 2
    with pytest.raises(ApiError, match='another request'):
        mutate(service, '/shopping/reset', {}, key=key)


def test_after_costco_copies(repo):
    seed(repo, 'costco', items='Milk', is_deleted=None)
    service = Service(repo)
    mutate(service, '/shopping/after-costco', {'ids': ['one']})
    lists = service.get('/shopping')
    assert lists['costco'][0]['items'] == 'Milk'
    assert lists['harris_teeter'][0]['items'] == 'Milk'


def test_null_not_false_means_active(repo):
    seed(repo, 'impromptu', 'a', name='active', is_deleted=None)
    seed(repo, 'impromptu', 'b', name='false', is_deleted=False)
    seed(repo, 'impromptu', 'c', name='deleted', is_deleted=True)
    assert [r['name'] for r in Service(repo).get('/impromptu')['items']] == ['active']


def test_reset_retains_history_and_new_entries_survive(repo):
    for kind in app.LISTS:
        for i in range(120):
            seed(repo, kind, str(i), is_deleted=None, **({'name': 'old'} if kind == 'impromptu' else {'items': 'old'}))
    seed(repo, 'impromptu', 'false', name='false', is_deleted=False)
    seed(repo, 'items', name='Eggs', location='Fridge', zone=3)
    seed(repo, 'meals', meal='Soup', last_eaten=None)
    service = Service(repo)
    mutate(service, '/shopping/reset', {})
    assert all(not service.get('/shopping')[kind] for kind in app.LISTS)
    assert len(repo.list('impromptu')) == 121
    assert visible(repo.get('impromptu', 'false'), repo.meta())['is_deleted'] is True
    assert len(service.get('/items')['items']) == len(service.get('/meals')['items']) == 1
    mutate(service, '/impromptu', {'name': 'new'})
    assert [r['name'] for r in service.get('/impromptu')['items']] == ['new']


def test_impromptu_delete(repo):
    row = seed(repo, 'impromptu', name='Bread', is_deleted=None)
    service = Service(repo)
    mutate(service, '/impromptu/one', {'version': 1}, 'DELETE')
    assert repo.get('impromptu', 'one')['is_deleted'] is True
    assert service.get('/impromptu')['items'] == []


def test_meal_tags_create_update_limit_and_preserve_other_fields(repo):
    service = Service(repo)
    mutate(service, '/meals', {'meal': 'Chicken bowl', 'tags': ['chicken', 'summer dish']})
    row = service.get('/meals')['items'][0]
    assert row['tags'] == ['chicken', 'summer dish']
    mutate(service, f'/meals/{row["id"]}', {'version': 1, 'tags': ['family favorite']}, 'PATCH')
    row = service.get('/meals')['items'][0]
    assert row['tags'] == ['family favorite'] and row['last_eaten'] is None and row['version'] == 2
    mutate(service, f'/meals/{row["id"]}', {'version': 2, 'last_eaten': '2026-01-02'}, 'PATCH')
    row = service.get('/meals')['items'][0]
    assert row['tags'] == ['family favorite'] and row['last_eaten'] == '2026-01-02'
    with pytest.raises(ApiError, match='at most 5 tags'):
        mutate(service, f'/meals/{row["id"]}', {'version': row['version'], 'tags': ['1', '2', '3', '4', '5', '6']}, 'PATCH')
    assert service.get('/meals')['items'][0]['tags'] == ['family favorite']


@pytest.mark.parametrize('tags', [
    'chicken', [''], ['   '], ['x' * 51], ['Chicken', 'chicken'], ['1', '2', '3', '4', '5', '6'],
])
def test_invalid_meal_tags_rejected(repo, tags):
    with pytest.raises(ApiError):
        mutate(Service(repo), '/meals', {'meal': 'Soup', 'tags': tags})
    assert Service(repo).get('/meals')['items'] == []


def test_public_meals_handler_returns_only_projection_fields(monkeypatch):
    class FakeTable:
        def __init__(self): self.calls = 0; self.meal_calls = 0
        def query(self, **kwargs):
            self.calls += 1
            if kwargs.get('Limit') == 1:
                return {'Items': [{'sync_state': 'ready'}]}
            self.meal_calls += 1
            if self.meal_calls == 1:
                return {'Items': [{'pk': 'PUBLIC#MEALS', 'sk': 'MEAL#1', 'meal': 'Soup',
                                   'tags': ['comfort'], 'last_eaten': '2026-01-01', 'private': 'hidden'}],
                        'LastEvaluatedKey': {'pk': 'PUBLIC#MEALS', 'sk': 'MEAL#2'}}
            return {'Items': [{'pk': 'PUBLIC#MEALS', 'sk': 'MEAL#2', 'meal': 'Egg quiche',
                               'private': 'hidden'}]}
    table = FakeTable()
    monkeypatch.setattr(public_meals, '_table', table)
    result = public_meals.lambda_handler({'requestContext': {'http': {'method': 'GET'}}, 'rawPath': '/'}, None)
    payload = json.loads(result['body'])
    assert result['statusCode'] == 200
    assert payload == {'meals': [
        {'meal': 'Egg quiche', 'tags': [], 'last_eaten': None},
        {'meal': 'Soup', 'tags': ['comfort'], 'last_eaten': '2026-01-01'},
    ]}
    assert table.calls == 3
    assert result['headers']['Content-Type'] == 'application/json'


def test_public_meals_handler_stays_unavailable_until_projection_is_ready(monkeypatch):
    class NotReady:
        def query(self, **kwargs): return {'Items': []}
    monkeypatch.setattr(public_meals, '_table', NotReady())
    result = public_meals.lambda_handler({'requestContext': {'http': {'method': 'GET'}}, 'rawPath': '/'}, None)
    assert result['statusCode'] == 503
    assert result['headers']['Retry-After'] == '30'


def test_public_meals_handler_rejects_writes(monkeypatch):
    class NeverQueried:
        def query(self, **kwargs): pytest.fail('Non-GET request must not read the table.')
    monkeypatch.setattr(public_meals, '_table', NeverQueried())
    result = public_meals.lambda_handler({'requestContext': {'http': {'method': 'POST'}}, 'rawPath': '/'}, None)
    assert result['statusCode'] == 405


def test_meals_date_sort_delete(repo):
    service = Service(repo)
    mutate(service, '/meals', {'meal': 'Soup'})
    row = service.get('/meals')['items'][0]
    with pytest.raises(ApiError, match='YYYY-MM-DD'):
        mutate(service, f'/meals/{row["id"]}', {'version': 1, 'last_eaten': '2026-02-30'}, 'PATCH')
    mutate(service, f'/meals/{row["id"]}', {'version': 1, 'last_eaten': '2026-01-02'}, 'PATCH')
    mutate(service, '/meals', {'meal': 'Pasta'})
    assert [r['meal'] for r in service.get('/meals')['items']] == ['Soup', 'Pasta']
    mutate(service, f'/meals/{row["id"]}', {'version': 2}, 'DELETE')
    assert repo.get('meals', row['id']) is None


@pytest.mark.parametrize('body', [{'entries': []}, {'entries': [{}]}, {'entries': [{}] * 91}, {'entries': 'bad'}])
def test_invalid_selections_atomic(repo, body):
    with pytest.raises(ApiError):
        mutate(Service(repo), '/shopping/selections', body)
    assert repo.meta()['revision'] == 0


def test_stale_meta_transaction_cannot_write(repo):
    old = repo.meta()
    new = dict(old, revision=old['revision'] + 1)
    assert repo.commit(old, new, [], [], str(uuid.uuid4()), 'hash', {'ok': True})
    assert not repo.commit(old, new, [], [], str(uuid.uuid4()), 'hash', {'ok': True})
    assert repo.meta()['revision'] == 1


def test_query_paginates(repo, monkeypatch):
    # Make every real DynamoDB query return one item per page.
    for i in range(4):
        seed(repo, 'items', str(i), name='Food', location='Pantry', zone=None)
    query = repo.client.query
    monkeypatch.setattr(repo.client, 'query', lambda **kwargs: query(**dict(kwargs, Limit=1)))
    assert len(repo.list('items')) == 4


def event(method='GET', path='/items', groups='[household]', body=None):
    return {'requestContext': {'http': {'method': method}, 'authorizer': {'jwt': {'claims': {'sub': 'user-1', 'cognito:groups': groups}}}},
            'rawPath': path, 'headers': {'Idempotency-Key': str(uuid.uuid4())}, 'body': json.dumps(body) if body is not None else None}


def test_handler_logs_dynamodb_timings_without_record_data(repo, monkeypatch, capsys):
    monkeypatch.setenv('DOMAIN', 'shopping')
    monkeypatch.setattr(app, '_repo', repo)
    seed(repo, 'impromptu', 'sensitive-id', name='private item', is_deleted=None)
    response = app.lambda_handler(event(path='/impromptu'), type('Context', (), {'aws_request_id': 'request-123'})())
    assert response['statusCode'] == 200
    log = json.loads(capsys.readouterr().out.strip())
    assert log['event'] == 'dynamodb_timing'
    assert log['requestId'] == 'request-123'
    assert log['route'] == 'GET /impromptu'
    assert isinstance(log['coldStart'], bool)
    assert log['repositoryInitMs'] is None
    assert [operation['operation'] for operation in log['operations']] == ['GetItem', 'Query']
    assert all(operation['durationMs'] >= 0 for operation in log['operations'])
    assert all('retryAttempts' in operation for operation in log['operations'])
    assert 'private item' not in json.dumps(log) and 'sensitive-id' not in json.dumps(log)


def test_handler_patch_uses_real_meal_id_and_sanitizes_only_log(repo, monkeypatch, capsys):
    monkeypatch.setenv('DOMAIN', 'meals')
    monkeypatch.setattr(app, '_repo', repo)
    seed(repo, 'meals', '21', meal='Egg quiche', last_eaten=None, tags=[])
    response = app.lambda_handler(event('PATCH', '/meals/21', body={'version': 1, 'tags': ['chicken']}), None)
    assert response['statusCode'] == 200
    assert repo.get('meals', '21')['tags'] == ['chicken']
    log = json.loads(capsys.readouterr().out.strip())
    assert log['route'] == 'PATCH /meals/{id}'
    meal_read = next(operation for operation in log['operations']
                     if operation['operation'] == 'GetItem' and operation.get('keyType') == 'MEALS')
    assert meal_read['itemCount'] == 1
    assert '21' not in json.dumps(log)


def test_handler_auth_and_domain(repo, monkeypatch):
    monkeypatch.setenv('DOMAIN', 'inventory')
    monkeypatch.setattr(app, '_repo', repo)
    assert app.lambda_handler({}, None)['statusCode'] == 401
    assert app.lambda_handler(event(groups='other'), None)['statusCode'] == 403
    assert app.lambda_handler(event(groups='[household, other]'), None)['statusCode'] == 200
    assert app.lambda_handler(event(path='/meals'), None)['statusCode'] == 404
    bad = event('POST', body={'name': 'Eggs'})
    bad['body'] = '{'
    assert app.lambda_handler(bad, None)['statusCode'] == 400
    bad['body'] = 'x' * 64001
    assert app.lambda_handler(bad, None)['statusCode'] == 413


def test_migration_lock(repo):
    repo.client.update_item(TableName=repo.table, Key=repo.pack({'pk': HOUSEHOLD, 'sk': 'META'}),
        UpdateExpression='SET migrationState = :state', ExpressionAttributeValues=repo.pack({':state': 'importing'}))
    with pytest.raises(ApiError) as error:
        Service(repo).get('/items')
    assert error.value.status == 503


def test_private_exports_validate_if_available():
    folder = ROOT / 'migration/private'
    if not (folder / 'items_rows(1).csv').exists():
        pytest.skip('Private exports intentionally excluded from Git')
    records, report = normalize(folder)
    assert not report['errors']
    assert len(records) == sum(t['sourceRows'] for t in report['tables'].values())
    assert len({r['sk'] for r in records}) == len(records)
    assert not any(r['kind'] in {'inventory', 'shopping_list'} for r in records)


def test_import_reconciliation_and_rerun(repo, monkeypatch):
    # Use an empty mocked AWS table; no real AWS services are contacted.
    repo.client.delete_item(TableName=repo.table, Key=repo.pack({'pk': HOUSEHOLD, 'sk': 'META'}))
    original_session = boto3.Session
    monkeypatch.setattr(boto3, 'Session', lambda **kwargs: original_session(region_name='us-east-1'))
    records = [{'pk': HOUSEHOLD, 'sk': 'ITEMS#1', 'id': '1', 'kind': 'items', 'name': 'Rice', 'location': 'Pantry', 'zone': None, 'version': 1, 'createdRevision': 0}]
    report = {'sourceFingerprint': 'abc'}
    apply(records, report, repo.table, 'test', '123456789012')
    assert repo.meta()['migrationState'] == 'ready'
    assert repo.get('items', '1')['name'] == 'Rice'
    apply(records, report, repo.table, 'test', '123456789012')
    with pytest.raises(RuntimeError, match='different fingerprint'):
        apply(records, {'sourceFingerprint': 'different'}, repo.table, 'test', '123456789012')


def test_full_private_migration_rehearsal(repo, monkeypatch):
    folder = ROOT / 'migration/private'
    if not (folder / 'items_rows(1).csv').exists():
        pytest.skip('Private exports intentionally excluded from Git')
    records, report = normalize(folder)
    assert not report['errors']
    repo.client.delete_item(TableName=repo.table, Key=repo.pack({'pk': HOUSEHOLD, 'sk': 'META'}))
    original_session = boto3.Session
    monkeypatch.setattr(boto3, 'Session', lambda **kwargs: original_session(region_name='us-east-1'))
    apply(records, report, repo.table, 'mock-only', '123456789012')
    actual = [row for kind in ['items', 'locations', 'meals', 'costco', 'harris_teeter', 'impromptu'] for row in repo.list(kind)]
    assert {row['sk']: row for row in actual} == {row['sk']: row for row in records}
    service = Service(repo)
    assert len(service.get('/items')['items']) == report['tables']['items']['sourceRows']
    assert len(service.get('/meals')['items']) == report['tables']['meals']['sourceRows']
    apply(records, report, repo.table, 'mock-only', '123456789012')
    result = {'mode': 'local Moto simulation; NO AWS services contacted',
              'recordsReconciled': len(actual), 'sourceFingerprint': report['sourceFingerprint'],
              'exactRecordComparison': 'passed', 'sameInputRerun': 'no writes',
              'activeLists': {kind: len(service.get('/shopping')[kind]) for kind in app.LISTS}}
    (folder / 'rehearsal-report.json').write_text(json.dumps(result, indent=2) + '\n')


def test_interrupted_import_resumes_same_input(repo, monkeypatch):
    original_session = boto3.Session
    monkeypatch.setattr(boto3, 'Session', lambda **kwargs: original_session(region_name='us-east-1'))
    meta = {'pk': HOUSEHOLD, 'sk': 'META', 'revision': 0, 'clearThrough': -1,
            'migrationState': 'importing', 'sourceFingerprint': 'resume-test'}
    repo.client.put_item(TableName=repo.table, Item=repo.pack(meta))
    row = {'pk': HOUSEHOLD, 'sk': 'MEALS#1', 'id': '1', 'kind': 'meals', 'meal': 'Soup',
           'last_eaten': None, 'version': 1, 'createdRevision': 0}
    repo.client.put_item(TableName=repo.table, Item=repo.pack(row))  # Existing partial batch
    apply([row], {'sourceFingerprint': 'resume-test'}, repo.table, 'mock-only', '123456789012')
    assert repo.meta()['migrationState'] == 'ready'
    assert len(repo.list('meals')) == 1


def test_import_account_guard(repo, monkeypatch):
    original_session = boto3.Session
    monkeypatch.setattr(boto3, 'Session', lambda **kwargs: original_session(region_name='us-east-1'))
    with pytest.raises(RuntimeError, match='account'):
        apply([], {'sourceFingerprint': 'abc'}, repo.table, 'test', '000000000000')
