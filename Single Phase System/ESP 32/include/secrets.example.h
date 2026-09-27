// Template for local credentials.
// Copy this file to secrets.h (git-ignored) and fill in real values.
#ifndef SECRETS_H_
#define SECRETS_H_

// eduroam (WPA2-Enterprise)
#define ssid "eduroam"
#define EAP_ANONYMOUS_IDENTITY "your-id@nottingham.edu.my"
#define EAP_IDENTITY "your-id@nottingham.edu.my"
#define EAP_PASSWORD "REDACTED"
#define EAP_USERNAME "your-id@nottingham.edu.my"

// Firebase Realtime Database
#define API_KEY "REDACTED"
#define DATABASE_URL "https://your-project-default-rtdb.region.firebasedatabase.app"
#define USER_EMAIL "REDACTED"
#define USER_PASSWORD "REDACTED"

// Fallback private Wi-Fi (WPA2-Personal)
#define ssid_private "REDACTED"
#define password_private "REDACTED"

#endif
