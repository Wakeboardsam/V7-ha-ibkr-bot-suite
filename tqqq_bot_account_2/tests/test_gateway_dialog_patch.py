import os
import re

def test_patch_logic():
    for addon_dir in ['tqqq_bot', 'tqqq_bot_account_2']:
        patch_file = os.path.join(os.path.dirname(__file__), '..', '..', addon_dir, 'gateway', 'patch', 'GatewayDialogHandler.java')

        assert os.path.exists(patch_file), f"Patch file missing: {patch_file}"

        with open(patch_file, 'r') as f:
            content = f.read()

        # 1. Recognize exact expired-token text in an if block
        assert 'text.contains("security tokens associated with your login credentials have expired")' in content, \
            f"Missing exact token expiration string match in {addon_dir}"

        # Split the file by the expired-token block and fallback block
        parts = content.split('text.contains("security tokens associated with your login credentials have expired")')
        assert len(parts) == 2, f"Expected exactly one expired token check in {addon_dir}"

        after_expired_check = parts[1]

        # Extract the block for token expiration (up to the 'else' for cold restart)
        expired_block_match = re.search(r'\{(.*?)\}\s*else\s*\{\s*Utils\.logToConsole\("Cold restart in progress"\);', after_expired_check, re.DOTALL)
        assert expired_block_match is not None, f"Could not isolate the expired-token logic block in {addon_dir}"
        expired_block = expired_block_match.group(1)

        # 2. OK is clicked in the expired-token branch
        assert 'SwingUtils.clickButton(window, "OK")' in expired_block, f"OK not clicked in expired-token branch in {addon_dir}"

        # 3. StopTask / cold restart is NOT present in the primary expired-token success branch
        retry_success_match = re.search(r'if \(!tokenExpiredRetryAttempted\)\s*\{(.*?)\}\s*else\s*\{\s*Utils\.logToConsole\("Token expired retry already attempted', expired_block, re.DOTALL)
        assert retry_success_match is not None, f"Could not find token retry success block in {addon_dir}"
        retry_success_block = retry_success_match.group(1)

        assert "StopTask" not in retry_success_block, f"StopTask found in the primary retry branch! in {addon_dir}"
        assert "Cold restart" not in retry_success_block, f"Cold restart found in the primary retry branch! in {addon_dir}"

        # 4. LoginManager login is invoked
        assert 'LoginManager.loginManager().setLoginState(LoginManager.LoginState.LOGGED_OUT)' in retry_success_block, \
            f"Did not reset login state in {addon_dir}"
        assert 'LoginManager.loginManager().getLoginHandler().initiateLogin' in retry_success_block, \
            f"Did not invoke initiateLogin in {addon_dir}"

        # 5. Loop prevention exists
        assert 'tokenExpiredRetryAttempted = true;' in retry_success_block, f"Loop prevention flag not set in {addon_dir}"

        # Check that fallback branch for retry failure has StopTask
        retry_failure_match = re.search(r'else\s*\{\s*Utils\.logToConsole\("Token expired retry already attempted for this process\. Falling back to cold restart\."\);(.*?)\}', expired_block, re.DOTALL)
        assert retry_failure_match is not None, f"Could not find retry failure fallback block in {addon_dir}"
        assert "StopTask" in retry_failure_match.group(1), f"StopTask missing from retry failure block in {addon_dir}"

        # 6. StopTask is present in the fallback "Connection to server failed" block (the main else)
        main_fallback_match = re.search(r'else\s*\{\s*Utils\.logToConsole\("Cold restart in progress"\);(.*?)\}', after_expired_check, re.DOTALL)
        assert main_fallback_match is not None, f"Could not find main cold restart fallback block in {addon_dir}"
        assert "StopTask" in main_fallback_match.group(1), f"StopTask missing from generic connection failed fallback in {addon_dir}"
