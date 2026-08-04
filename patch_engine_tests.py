def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    s1 = "with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock):"
    r1 = "with patch.object(engine, '_check_reconciliation_and_halt', new_callable=AsyncMock) as mock_chk:\n        mock_chk.return_value = False"
    content = content.replace(s1, r1)

    s2 = "engine._check_reconciliation_and_halt = AsyncMock()"
    r2 = "engine._check_reconciliation_and_halt = AsyncMock(return_value=False)"
    content = content.replace(s2, r2)

    with open(filepath, 'w') as f:
        f.write(content)

patch_file('tqqq_bot/tests/test_reconciliation.py')
patch_file('tqqq_bot_account_2/tests/test_reconciliation.py')
patch_file('tqqq_bot/tests/test_session_boundary_cancellations.py')
patch_file('tqqq_bot_account_2/tests/test_session_boundary_cancellations.py')
patch_file('tqqq_bot/tests/test_engine.py')
patch_file('tqqq_bot_account_2/tests/test_engine.py')
