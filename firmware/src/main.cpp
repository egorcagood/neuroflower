#include <Arduino.h>
#include <Wire.h>
#include <BH1750.h>
#include <Adafruit_SHT31.h>
#include <math.h>
#include <initializer_list>

class SensorConsole : public Print {
public:
  void begin(unsigned long baud) {
    Serial0.begin(baud);
    Serial.begin(baud);
    Serial.setTxTimeoutMs(0);
  }
  size_t write(uint8_t value) override { return write(&value, 1); }
  size_t write(const uint8_t *data, size_t length) override {
    Serial.write(data, length);
    return Serial0.write(data, length);
  }
};
SensorConsole console;

constexpr int SOIL_PIN = 4;
constexpr int SDA_PIN = 8;
constexpr int SCL_PIN = 9;
BH1750 lightMeter;
Adafruit_SHT31 airSensor(&Wire);
bool lightReady = false;
bool airReady = false;
bool i2cReady = false;

bool present(uint8_t address) {
  if (!i2cReady || digitalRead(SDA_PIN) == LOW || digitalRead(SCL_PIN) == LOW) return false;
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

void initSensors() {
  if (!lightReady) {
    for (uint8_t address : {0x23, 0x5C}) {
      if (present(address)) {
        lightReady = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, address, &Wire);
        if (lightReady) break;
      }
    }
  }
  if (!airReady) {
    for (uint8_t address : {0x44, 0x45}) {
      if (present(address)) {
        airReady = airSensor.begin(address);
        if (airReady) {
          airSensor.heater(false);
          break;
        }
      }
    }
  }
}

void setup() {
  console.begin(115200);
  for (int i = 0; i < 6; ++i) {
    console.println("USB_STARTUP");
    delay(500);
  }
  console.println("\nPLANT SENSOR TEST: NO PUMP CONTROL");
  console.println("3V3 only; SOIL=GPIO4 SDA=GPIO8 SCL=GPIO9");
  console.printf("Chip: %s, flash: %u bytes\n", ESP.getChipModel(), ESP.getFlashChipSize());
  console.println("Initializing GPIO4 ADC...");
  pinMode(SOIL_PIN, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(SOIL_PIN, ADC_11db);
  console.println("ADC ready; initializing I2C...");
  i2cReady = Wire.begin(SDA_PIN, SCL_PIN, 100000);
  Wire.setTimeOut(50);
  console.printf("I2C begin=%d SDA=%d SCL=%d\n", i2cReady, digitalRead(SDA_PIN), digitalRead(SCL_PIN));
  for (uint8_t address : {0x23, 0x5C, 0x44, 0x45}) {
    console.printf("Checking I2C address 0x%02X...\n", address);
    console.printf("I2C 0x%02X present=%d\n", address, present(address));
  }
  console.println();
  initSensors();
  delay(200);
}

void loop() {
  initSensors();
  uint32_t raw = 0, mv = 0;
  for (int i = 0; i < 32; ++i) {
    raw += analogRead(SOIL_PIN);
    mv += analogReadMilliVolts(SOIL_PIN);
    delay(1);
  }
  console.printf("uptime_s=%lu | soil_raw=%lu/4095 | soil_mV=%lu (uncalibrated)",
                millis() / 1000UL, raw / 32UL, mv / 32UL);
  if (!i2cReady || digitalRead(SDA_PIN) == LOW || digitalRead(SCL_PIN) == LOW)
    console.printf(" | I2C_BUS_NOT_IDLE SDA=%d SCL=%d", digitalRead(SDA_PIN), digitalRead(SCL_PIN));
  float measuredLux = NAN;
  if (lightReady) {
    const float lux = lightMeter.readLightLevel();
    if (isfinite(lux) && lux>=0) measuredLux=lux;
    if (isfinite(lux) && lux >= 0) console.printf(" | light_lux=%.1f", lux);
    else {
      console.print(" | BH1750=READ_ERROR");
      lightReady = false;
    }
  } else console.print(" | BH1750=NOT_FOUND");
  float temperature = NAN, humidity = NAN;
  if (airReady && airSensor.readBoth(&temperature, &humidity) &&
      isfinite(temperature) && isfinite(humidity)) {
    console.printf(" | temperature_C=%.2f | air_RH_pct=%.2f", temperature, humidity);
  } else {
    console.print(airReady ? " | SHT30=READ_ERROR" : " | SHT30=NOT_FOUND");
    airReady = false;
    temperature = humidity = NAN;
  }
  console.println();
  delay(2000);
}
