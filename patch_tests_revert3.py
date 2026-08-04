def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    s1 = "engine._check_reconciliation_and_halt = AsyncMock()"
    r1 = "engine._check_reconciliation_and_halt = AsyncMock(return_value=False)"
    content = content.replace(s1, r1)

    with open(filepath, 'w') as f:
        f.write(content)

patch_file('tqqq_bot/tests/test_session_boundary_cancellations.py')
patch_file('tqqq_bot_account_2/tests/test_session_boundary_cancellations.py')
