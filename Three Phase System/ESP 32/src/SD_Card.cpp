#include "SD_Card.h"
#define SCK 18
#define MISO 19
#define MOSI 23
#define CS 5
static SDCARD *instance = NULL;
int id = 0;

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
        String header = "ID,TimeStamp,Voltage1,Current1,Power1,Voltage2,Current2,Power2,Voltage3,Current3,Power3";
        dataFile.println(header);
        dataFile.close();
        Serial.println(header);
    }
    else{
        Serial.println("Couldnt Access File");
    }
}

void SDCARD::logData(String timestamp, double voltage1, double current1, double power1, double voltage2, double current2, double power2,double voltage3, double current3, double power3){
    
    String DataString = String(id) + "," + String(timestamp) + "," + String(voltage1) + "," + String(current1)+ "," + String(power1) +"," +String(voltage2) + "," + String(current2)+ "," + String(power2) + "," + String(voltage3) + "," + String(current3) + "," + String(power3);

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