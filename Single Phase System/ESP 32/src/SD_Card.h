#ifndef SD_Card_H_
#define SD_Card_H_
#include "SD.h"
#include "FS.h"
#include "SPI.h"

class SDCARD{


public:
    SDCARD();
    void initSD();
    void FileHeader();
    void logData(String timestamp, double voltage, double current, double power);
};



#endif