#!/bin/bash
# Sign and notarize Protagonist.app for macOS distribution.
#
# Prerequisites:
#   1. Apple Developer account ($99/year)
#   2. Developer ID Application certificate installed in Keychain
#   3. App-specific password for notarytool
#
# Set these environment variables before running:
#   DEVELOPER_ID  - e.g. "Developer ID Application: Your Name (TEAM_ID)"
#   APPLE_ID      - your Apple ID email
#   TEAM_ID       - your 10-char team ID
#   APP_PASSWORD  - app-specific password from appleid.apple.com
#
# Usage:
#   export DEVELOPER_ID="Developer ID Application: ..."
#   export APPLE_ID="you@example.com"
#   export TEAM_ID="XXXXXXXXXX"
#   export APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
#   ./scripts/sign_and_notarize.sh

set -euo pipefail

APP_PATH="dist/Protagonist.app"
DMG_PATH="dist/Protagonist.dmg"

# --- Validate env ---
for var in DEVELOPER_ID APPLE_ID TEAM_ID APP_PASSWORD; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set."
        exit 1
    fi
done

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: $APP_PATH not found. Run 'python setup.py py2app' first."
    exit 1
fi

echo "==> Signing $APP_PATH ..."
codesign --deep --force --options runtime \
    --sign "$DEVELOPER_ID" \
    "$APP_PATH"

echo "==> Verifying signature ..."
codesign --verify --deep --strict "$APP_PATH"
spctl --assess --type execute "$APP_PATH"

echo "==> Creating DMG ..."
if [ -f "$DMG_PATH" ]; then
    rm "$DMG_PATH"
fi
hdiutil create -volname "Protagonist" \
    -srcfolder "$APP_PATH" \
    -ov -format UDZO \
    "$DMG_PATH"

echo "==> Signing DMG ..."
codesign --force --sign "$DEVELOPER_ID" "$DMG_PATH"

echo "==> Submitting for notarization ..."
xcrun notarytool submit "$DMG_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$TEAM_ID" \
    --password "$APP_PASSWORD" \
    --wait

echo "==> Stapling notarization ticket ..."
xcrun stapler staple "$DMG_PATH"

echo ""
echo "Done! $DMG_PATH is signed and notarized."
echo "Users can install it without Gatekeeper warnings."
