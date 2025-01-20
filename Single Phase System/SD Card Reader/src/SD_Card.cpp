#include "SD_Card.h"
#define SCK 18
#define MISO 19
#define MOSI 23
#define CS 5
static SDCARD *instance = NULL;


SDCARD::SDCARD(){
    instance =this;
}

void SDCARD::initSD(){

    if(!SD.begin(5)){
        Serial.println("Card Mount Failed");
        return;
    }
    uint8_t cardType = SD.cardType();

    if(cardType == CARD_NONE){
        Serial.println("No SD card attached");
        return;
    }

    Serial.print("SD Card Type: ");
    if(cardType == CARD_MMC){
        Serial.println("MMC");
    } else if(cardType == CARD_SD){
        Serial.println("SDSC");
    } else if(cardType == CARD_SDHC){
        Serial.println("SDHC");
    } else {
        Serial.println("UNKNOWN");
    }

    uint64_t cardSize = SD.cardSize() / (1024 * 1024);
    Serial.printf("SD Card Size: %lluMB\n", cardSize);

}

void SDCARD::FileHeader(){
    File dataFile = SD.open("/log.csv",FILE_WRITE);
    if (dataFile){
        dataFile.println(", , , ,");
        String header = "ID,TimeStamp,Current,Voltage,Power";
        dataFile.println(header);
        dataFile.close();
        Serial.println(header);
    }
    else{
        Serial.println("Couldnt Access File");
    }
}

void SDCARD::logData(double timestamp, double voltage, double current, double power){
    String DataString = String(id) + "," + String(timestamp) + "," + String(voltage) + "," + String(current)+ "," + String(power);

    File dataFile = SD.open("/log.csv",FILE_APPEND);
    if (dataFile){
        dataFile.println(DataString);
        dataFile.close();
        Serial.println(DataString);
    }
    else{
        Serial.println("Couldnt Access File");
    }

    id++;
}