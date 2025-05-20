#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define RED_LED 26
#define GREEN_LED 27

const char* ssid = "Wokwi-GUEST";
const char* password = "";

const char* mqttServer = "broker.emqx.io";
const int mqttPort = 1883;


const char* commandTopic = "smartlock/commands";
const char* statusTopic  = "smartlock/status";

// MQTT authentication
const char* mqttUsername = "esp32";
const char* mqttPassword = "pssword";

WiFiClient espClient;
PubSubClient client(espClient);

String clientId;
String currentState = "Unknown";

void sendStatusToMQTT(String status, String state = "") {
  StaticJsonDocument<256> doc;
  doc["device"] = "device-1";
  doc["status"] = status;
  doc["state"] = state;

  char buffer[256];
  size_t len = serializeJson(doc, buffer);

  if (client.connected()) {
    bool success = client.publish(statusTopic, buffer, len);
    Serial.print("MQTT Status sent: ");
    Serial.println(success ? "Success" : "Failed");
  } else {
    Serial.println("MQTT not connected. Cannot send status.");
  }
}


void setup() {
  Serial.begin(115200);
  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected to WiFi");

  client.setServer(mqttServer, mqttPort);
  client.setCallback(mqttCallback);

  sendStatusToMQTT("Booted");
}

void loop() {
  if (!client.connected()) {
    reconnectMQTT();
  }

  client.loop();

  static unsigned long lastUpdate = 0;
  if (millis() - lastUpdate > 9000) {
    sendStatusToMQTT("Online", currentState);
    lastUpdate = millis();
  }

  delay(500);
}

void reconnectMQTT() {
  clientId = "ESP32Client-" + String(WiFi.macAddress());

  while (!client.connected()) {
    Serial.print("Connecting to MQTT...");
    if (client.connect(clientId.c_str(), mqttUsername, mqttPassword)) {
      Serial.println("Connected to MQTT");
      client.subscribe(commandTopic);
    } else {
      Serial.print("Failed, rc=");
      Serial.println(client.state());
      delay(2000);
    }
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("MQTT Message on [");
  Serial.print(topic);
  Serial.print("]: ");

  String message;
  for (int i = 0; i < length; i++) message += (char)payload[i];
  Serial.println(message);

  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, message);
  if (err) {
    Serial.print("JSON parse error: ");
    Serial.println(err.c_str());
    return;
  }

  const char* command = doc["command"];


  if (String(command) == "LOCK") {
    digitalWrite(RED_LED, HIGH);
    digitalWrite(GREEN_LED, LOW);
    currentState = "Locked";
    sendStatusToMQTT("Locked", currentState);
  } else if (String(command) == "UNLOCK") {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
    currentState = "Unlocked";
    sendStatusToMQTT("Unlocked", currentState);
  } else {
    Serial.println("Unknown command");
  }
}

