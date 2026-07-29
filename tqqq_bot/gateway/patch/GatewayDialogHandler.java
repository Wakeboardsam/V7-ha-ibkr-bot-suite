// This file is part of IBC.
// Copyright (C) 2004 Steven M. Kearns (skearns23@yahoo.com )
// Copyright (C) 2004 - 2025 Richard L King (rlking@aultan.com)
// For conditions of distribution and use, see copyright notice in COPYING.txt

// IBC is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

// IBC is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.

// You should have received a copy of the GNU General Public License
// along with IBC.  If not, see <http://www.gnu.org/licenses/>.

package ibcalpha.ibc;

import java.awt.Window;
import java.awt.event.WindowEvent;
import java.util.concurrent.TimeUnit;
import javax.swing.JDialog;
import javax.swing.JFrame;

public class GatewayDialogHandler implements WindowHandler {

    private static boolean tokenExpiredRetryAttempted = false;

    private boolean isExpiredTokenDialog(Window window) {
        if (!(window instanceof JDialog)) return false;
        return SwingUtils.getWindowStructure(window)
            .toLowerCase(java.util.Locale.ROOT)
            .contains("security tokens associated with your login credentials have expired");
    }

    @Override
    public boolean filterEvent(Window window, int eventId) {
        switch (eventId) {
            case WindowEvent.WINDOW_OPENED:
                return true;
            default:
                return false;
        }
    }

    @Override
    public void handleWindow(Window window, int eventID) {
        if (isExpiredTokenDialog(window)) {
            Utils.logToConsole("GATEWAY_AUTH_TOKEN_EXPIRED");
            if (SwingUtils.clickButton(window, "OK")) {
                Utils.logToConsole("Expired-token dialog dismissed");
                if (!tokenExpiredRetryAttempted) {
                    tokenExpiredRetryAttempted = true;
                    Utils.logToConsole("Retrying Gateway login with configured credentials");

                    // Schedule the retry slightly in the future to allow the dialog to close completely
                    MyScheduledExecutorService.getInstance().schedule(() -> {
                        GuiDeferredExecutor.instance().execute(() -> {
                            LoginManager.loginManager().setLoginState(LoginManager.LoginState.LOGGED_OUT);
                            JFrame loginFrame = LoginManager.loginManager().getLoginFrame();
                            if (loginFrame != null) {
                                if (LoginManager.loginManager().getLoginHandler() != null) {
                                    LoginManager.loginManager().getLoginHandler().initiateLogin(loginFrame);
                                } else {
                                    Utils.logError("Cannot retry login: login handler not found.");
                                }
                            } else {
                                Utils.logError("Cannot retry login: login frame not found.");
                            }
                        });
                    }, 2, TimeUnit.SECONDS);
                } else {
                    Utils.logToConsole("Token expired retry already attempted for this process. Falling back to cold restart.");
                    MyCachedThreadPool.getInstance().execute(new StopTask(null, true, "Cold restart after repeated Connection to server failed"));
                }
            } else {
                Utils.logError("could not dismiss Login Error dialog because we could not find the OK button");
            }
            return;
        }

        String text = SwingUtils.getLabelTexts(window);
        // since this is a generic dialog, we always log the text
        Utils.logToConsole(text);
        if (text.startsWith("Connection to server failed")) {
            Utils.logToConsole("Cold restart in progress");
            // stop tidily and do a cold restart
            MyCachedThreadPool.getInstance().execute(new StopTask(null, true, "Cold restart after Connection to server failed"));

            if (! SwingUtils.clickButton(window, "OK")) {
                Utils.logError("could not dismiss Login Error dialog because we could not find the OK button");
            }
        } else {
            // for other instances of this dialog, just leave it on display for the user to handle. For example,
            // it is used when setting Trusted IP addresses in the Gateway
        }
    }

    @Override
    public boolean recogniseWindow(Window window) {
        if (isExpiredTokenDialog(window)) {
            return true;
        }

        if (! (window instanceof JDialog)) return false;

        return (SwingUtils.titleContains(window, "Gateway"));
    }

}
