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
    String currPath1 = "/current1";
    String voltPath1 = "/voltage1";
    String powerPath1 = "/power1";
    String currPath2 = "/current2";
    String voltPath2 = "/voltage2";
    String powerPath2 = "/power2";
    String currPath3 = "/current3";
    String voltPath3 = "/voltage3";
    String powerPath3 = "/power3";
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
    void RTDBUpdate(String timestamp, double voltage1, double current1, double power1, double voltage2, double current2, double power2, double voltage3, double current3, double power3);



};



#endif