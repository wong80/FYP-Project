#include <Arduino.h>
#include "SD_Card.h"

SDCARD *sdcard;

void initSD_Card(){
  sdcard = new SDCARD();
  sdcard->initSD();
}

void setup() {
  // put your setup code here, to run once:
 Serial.begin(115200);
 initSD_Card();
 sdcard->FileHeader();
}

void loop() {
  sdcard->logData(500,123,123,412);
  delay(1000);
}