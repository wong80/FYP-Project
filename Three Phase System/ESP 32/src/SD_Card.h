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
    void logData(String timestamp, double voltage1, double current1, double power1, double voltage2, double current2, double power2, double voltage3, double current3, double power3);
};



#endif