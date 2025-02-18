#include "Network.h"
#include "addons/TokenHelper.h"
#include "addons/RTDBHelper.h"
#define ssid "eduroam"
#define EAP_ANONYMOUS_IDENTITY "REDACTED" 
#define EAP_IDENTITY "REDACTED" 
#define EAP_PASSWORD "REDACTED" 
#define EAP_USERNAME "REDACTED" 
#define API_KEY "REDACTED"
#define DATABASE_URL "https://fyp-powermonitoring-b2afc-default-rtdb.asia-southeast1.firebasedatabase.app"
#define USER_EMAIL "REDACTED"
#define USER_PASSWORD "REDACTED"

#define ssid_private "REDACTED"
#define password_private "REDACTED"

static Network *instance = NULL;
int firebase_id = 0;

Network::Network(){
  instance = this;
}


void Network::initWiFi(){

  WiFi.begin(ssid, WPA2_AUTH_PEAP, EAP_IDENTITY, EAP_USERNAME, EAP_PASSWORD);
  Serial.print("Connecting to WiFi ..");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print('.');
    delay(1000);
  }
  Serial.println(WiFi.localIP());
  Serial.println();
  instance->initFirebase();
};

void Network::initFirebase(){
  // Assign the api key (required)
  config.api_key = API_KEY;

  // Assign the user sign in credentials
  auth.user.email = USER_EMAIL;
  auth.user.password = USER_PASSWORD;

  // Assign the RTDB URL (required)
  config.database_url = DATABASE_URL;

  Firebase.reconnectWiFi(true);
  fbdo.setResponseSize(4096);

  // Assign the callback function for the long running token generation task */
  // config.token_status_callback = tokenStatusCallback; //see addons/TokenHelper.h

  // Assign the maximum retry of token generation
  config.max_token_generation_retry = 5;

  // Initialize the library with the Firebase authen and config
  Firebase.begin(&config, &auth);

  // Getting the user UID might take a few seconds
  Serial.println("Getting User UID");
  while ((auth.token.uid) == "") {
    Serial.print('.');
    delay(1000);
  }
  // Print user UID
  uid = auth.token.uid.c_str();
  Serial.print("User UID: ");
  Serial.println(uid);

  // Update database path
  databasePath = "/UsersData/" + uid + "/readings";

};

void Network::RTDBUpdate(String timestamp, double voltage1, double current1, double power1, double voltage2, double current2, double power2, double voltage3, double current3, double power3){
   // Send new readings to database
  if (Firebase.ready() && (millis() - sendDataPrevMillis > timerDelay || sendDataPrevMillis == 0)){
    sendDataPrevMillis = millis();

    parentPath= databasePath + "/" + String(firebase_id);
    json.set(timePath, String(timestamp));
    json.set(voltPath1.c_str(), String(voltage1));
    json.set(currPath1.c_str(), String(current1));
    json.set(powerPath1.c_str(), String(power1));
    json.set(voltPath2.c_str(), String(voltage2));
    json.set(currPath2.c_str(), String(current2));
    json.set(powerPath2.c_str(), String(power2));
    json.set(voltPath3.c_str(), String(voltage3));
    json.set(currPath3.c_str(), String(current3));
    json.set(powerPath3.c_str(), String(power3));
    Serial.printf("Set json... %s\n", Firebase.RTDB.setJSON(&fbdo, parentPath.c_str(), &json) ? "ok" : fbdo.errorReason().c_str());
    firebase_id++;
  }
  
};