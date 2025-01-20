#ifndef Network_H_
#define Network_H_



#include "Network.h"
#include <WiFi.h> //Wifi library
#include "esp_wpa2.h"
#include <Firebase_ESP_Client.h>



class Network{
    private:
    // Define Firebase objects
    FirebaseData fbdo;
    FirebaseAuth auth;
    FirebaseConfig config;
    FirebaseJson json;
    unsigned long sendDataPrevMillis = 0;
    unsigned long timerDelay = 18000;
    String uid;
    String databasePath;
    String currPath = "/current";
    String voltPath = "/voltage";
    String powerPath = "/power";
    String timePath = "/timestamp";
    String parentPath;
    float temperature;
    float humidity;
    float pressure;

    int timestamp;

    public:
    Network();
    void initWiFi();
    void initFirebase();
    void RTDBUpdate(String timestamp, double voltage, double current, double power);



};



#endif