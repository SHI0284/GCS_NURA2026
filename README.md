# NURA Ground Control System

NURA 로켓의 텔레메트리를 실시간으로 수신·기록하고, 비행 상태와 GPS 위치를 시각화하며, 인증된 `SAFE → ARMED` 및 PYRO 명령을 전송하는 최종 웹 기반 지상국입니다.

현재 주 운용 화면은 `mission_control.html`, 서버는 `app.py`입니다. `desktop.py`는 이전 PyQt 보조 화면으로 유지되며 실제 운용의 기준이 아닙니다.

> [!CAUTION]
> 이 소프트웨어의 ACK는 항전 컴퓨터가 명령을 수신하고 실행 경로를 완료했다는 뜻입니다. 점화 회로의 전기적 연속성, 실제 화약 점화 또는 낙하산 전개를 독립적으로 증명하지 않습니다. 실제 PYRO가 연결된 상태에서는 승인된 현장 절차와 충분한 안전거리를 반드시 지키십시오.

## 주요 기능

- NURA V2 Lite 인증 프레임의 Vehicle ID, 방향, MAC, CRC 검증
- FAST/GPS/CONTROL 텔레메트리 실시간 수신 및 자동 재연결
- 고도, 가속도, 자세, 배터리, GPS, RSSI/SNR, 비행 상태 표시
- Chart.js 기반 시계열 그래프와 Leaflet 기반 GPS 지도
- 기체 좌표계로 보정된 2D 로켓 자세 시각화
- 모든 하드웨어 패킷과 수신 진단 값을 CSV로 즉시 기록
- 인증된 `SAFE → ARMED` 전이와 `EXECUTED/OK + ARMED` ACK 확인
- 이중 확인을 거치는 PYRO 강제 전개 명령
- 패킷 누락·중복·역순, 프레임 거부, 브리지/무선 상태 진단
- 하드웨어 없이 전체 UI와 명령 흐름을 확인하는 시뮬레이션 모드

## 시스템 구성

```text
┌─────────────────────────────── Ground Station PC ───────────────────────────────┐
│                                                                                │
│  mission_control.html  ⇄  app.py  ⇄  uplink.py  ⇄  protocol.py                │
│       UI/지도/그래프       Flask       명령/재전송      프레임 인증·해석          │
│                                 │                                              │
│                                 └──────── logs/hardware_log_*.csv              │
└─────────────────────────────────┬──────────────────────────────────────────────┘
                                  │ USB Serial 115200 bps / raw frame
                         Teensy 4.1 Ground Bridge
                                  │
                     SparkFun 1W SX1276 또는 LR900-F
                                  │ LoRa
                           Rocket Avionics
```

기본 운용 경로는 `PC → USB Teensy 브리지 → LoRa → 항전 컴퓨터`입니다. 브리지는 무선 프레임을 변경하지 않고 양방향 전달하며, 인증과 텔레메트리 해석은 PC의 `protocol.py`에서 수행합니다.

## 빠른 시작

### 1. 시뮬레이션

Python 3.10 이상을 권장합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
python tools/prepare_web_assets.py
python app.py --simulate
```

브라우저에서 <http://127.0.0.1:8080>을 열면 됩니다. Windows에서는 아래 배치 파일로 같은 모드를 실행할 수 있습니다.

```bat
run_web_simulate.bat
```

### 2. Linux 하드웨어 운용

`run_ground_station.sh`는 선택한 지상국 Teensy만 대상으로 다음 작업을 한 번에 수행합니다.

1. 로컬 `.venv` 및 웹 의존성 준비
2. Chart.js/Leaflet 정적 파일 검증 및 로컬 캐시
3. 브리지 펌웨어 빌드
4. 지정한 Teensy에만 펌웨어 업로드
5. 포트 재등장과 무선 초기화 확인
6. Flask 서버 실행 및 브라우저 열기

```bash
chmod +x run_ground_station.sh
./run_ground_station.sh \
  --port /dev/serial/by-id/usb-Teensyduino_USB_Serial_19957540-if00
```

`--port`는 필수입니다. 여러 Teensy가 연결된 상황에서 항전용 보드를 잘못 플래시하지 않도록 자동 포트 선택을 하지 않습니다. `/dev/ttyACM*`보다 `/dev/serial/by-id/*` 경로 사용을 권장합니다.

필요 도구는 Python 3, PlatformIO(`pio`), `udevadm`, Teensy PlatformIO 도구입니다. 브리지 빌드는 기본적으로 GCS와 같은 상위 폴더의 `2026-nura-avionics` 프로토콜 헤더를 참조합니다.

```text
workspace/
├── GCS/
└── 2026-nura-avionics/
```

주요 실행 옵션:

| 옵션 | 설명 |
| --- | --- |
| `--port PORT` | 지상국 Teensy 포트, 필수 |
| `--firmware-env ENV` | PlatformIO 환경, 기본값 `sx1276_ground` |
| `--host HOST` | Flask bind 주소, 기본값 `127.0.0.1` |
| `--http-port PORT` | 웹 포트, 기본값 `8080` |
| `--no-browser` | 브라우저 자동 실행 안 함 |
| `--allow-public-bench-arm` | 공개 테스트 키의 ARM을 벤치에서만 명시적으로 허용 |

이미 펌웨어가 올라가 있고 서버만 직접 실행할 때는 다음 명령을 사용합니다.

```bash
.venv/bin/python app.py \
  --serial-port /dev/serial/by-id/usb-Teensyduino_USB_Serial_19957540-if00 \
  --serial-mode raw
```

Windows에서는 브리지 펌웨어를 별도로 업로드한 뒤 다음을 실행합니다.

```bat
run_web_hardware.bat COM5
```

## 무선 브리지

### SparkFun 1W SX1276 — 기본 구성

기본 PlatformIO 환경 `sx1276_ground`는 SparkFun LoRa 1W Breakout SPX-18572/E19-915M30S와 Teensy 4.1 조합입니다. 최종 항전 보드의 `BoardPinMap::Sx1276BreakoutLoRa`와 같은 SPI1 배선을 사용합니다.

| SparkFun 신호 | Teensy 4.1 |
| --- | --- |
| `CIPO` / `MISO` | `MISO1`, pin 1 |
| `COPI` / `MOSI` | `MOSI1`, pin 26 |
| `SCK` | `SCK1`, pin 27 |
| `NSS` / `CS` | pin 9 |
| `RST` | pin 24 |
| `DIO0` | pin 32 |
| `RXEN` | pin 30 |
| `TXEN` | pin 31 |
| `DIO1` | 미사용 |
| `3.3V` | 3.3 V 로직 전원 |
| `5V` | 5 V 모듈/PA 전원 |
| `GND` | 공통 GND |

`RXEN`과 `TXEN`은 active-high이며 수신은 `(1,0)`, 송신은 `(0,1)`, idle은 `(0,0)`입니다. 5 V와 3.3 V 전원을 모두 연결하고, 송신 전 반드시 적합한 915 MHz 안테나를 장착하십시오.

기존 SPI0 하네스를 사용해야 하는 경우에만 다음 환경을 선택합니다.

```bash
./run_ground_station.sh --port /dev/ttyACM1 \
  --firmware-env sx1276_ground_legacy_spi0
```

### LR900-F — 선택 구성

LR900-F는 Teensy 4.1의 `Serial1`을 사용하는 UART 브리지입니다. PC USB는 115200 bps, LR900-F 측은 기본 57600 bps입니다.

| LR900-F JST-GH | Teensy 4.1 |
| --- | --- |
| `G` / GND | GND |
| `V` / VCC | 5V/VIN |
| `R` / RX | TX1, pin 1 |
| `T` / TX | RX1, pin 0 |

```bash
./run_ground_station.sh --port /dev/ttyACM1 \
  --firmware-env lr900f_teensy41
```

## 무선 인증 정보

실제 비행에서는 GCS와 항전 펌웨어에 동일한 전용 Vehicle ID와 128-bit 인증 키를 설정해야 합니다.

```bash
export NURA_RADIO_VEHICLE_ID=0x........
export NURA_RADIO_AUTH_KEY_HEX=<32개의 16진수 문자>
./run_ground_station.sh --port /dev/serial/by-id/usb-Teensyduino_USB_Serial_...
```

두 값은 항전 저장소의 `include/nura_radio_secrets.h`와 정확히 일치해야 합니다. 둘 중 하나만 설정하면 서버가 시작되지 않습니다. 둘 다 없으면 공개 벤치 ID/키를 사용하며, 이는 비행용으로 안전하지 않습니다.

공개 벤치 ID에서 ARM은 기본 차단됩니다. 실물 PYRO를 분리한 벤치 시험에서만 다음 옵션으로 명시적으로 허용할 수 있습니다.

```bash
./run_ground_station.sh --port /dev/ttyACM1 --allow-public-bench-arm
```

이 옵션은 공개 ID를 비행용으로 승격하지 않습니다.

## 운용 흐름

1. 지상국 Teensy와 무선 모듈, 안테나, USB를 연결합니다.
2. 전용 무선 ID/키가 GCS와 항전에 동일한지 확인합니다.
3. `run_ground_station.sh`로 지상국을 실행합니다.
4. 헤더의 링크·무선·GPS 상태와 텔레메트리 갱신을 확인합니다.
5. `/api/telemetry/status` 또는 패킷 모니터로 프레임 거부와 누락 여부를 확인합니다.
6. 승인된 절차에 따라 `SAFE → ARMED`를 실행하고 ARMED ACK 및 후속 FAST 상태를 확인합니다.
7. 비행 중 지도, 그래프, 상태와 로그 기록을 감시합니다.
8. 종료 후 `logs/hardware_log_*.csv`를 보존합니다.

### SAFE → ARMED 안전 조건

UI에서 ARM 모달을 열고 현장 안전 확인 체크박스를 선택하면 브라우저가 아래 요청을 보냅니다.

```http
POST /api/flight/arm
Content-Type: application/json

{"confirm":"ARM","expected_state":1}
```

서버는 다음 조건을 모두 만족할 때만 명령을 생성하고 전송합니다.

- 지상국 브리지가 연결되고 `raw` 모드일 것
- 실제 비행용 무선 ID/키가 설정되어 있을 것
- 항전 업링크가 활성화되어 있을 것
- 브리지 무선 초기화가 성공했을 것
- 1.5초 이내의 인증된 FAST 텔레메트리가 정확히 `SAFE(1)`일 것
- 항전 boot clock을 기준으로 3초의 명령 만료 시간을 만들 수 있을 것

성공 판정은 `EXECUTED/OK` ACK의 최종 상태가 `ARMED(2)`일 때뿐입니다. `ACCEPTED`나 중간 `DUPLICATE/SAFE`는 성공으로 처리하지 않습니다.

```bash
curl http://127.0.0.1:8080/api/flight/arm/status
```

항전 소스가 `kFlightDownlinkOnly=true`이면 ARM, PYRO 및 하드웨어 FSM reset 업링크는 의도적으로 차단됩니다. GCS는 이 안전 설정을 자동 변경하지 않습니다. 자세한 항전 연동 계약은 [`AVIONICS_ARM_UPLINK_HANDOFF_KR.md`](AVIONICS_ARM_UPLINK_HANDOFF_KR.md)를 참고하십시오.

### PYRO 강제 전개

Mission Control의 EJECT/PYRO 모달은 서버에 `{"confirm":"DEPLOY"}`를 전송합니다. 서버는 인증된 명령을 재전송하고 `EXECUTED` ACK를 확인합니다. 이 기능은 정상 자동 전개 로직의 대체 수단이 아니라 승인된 시험·비상 절차용입니다.

## 데이터와 진단

하드웨어 모드는 실행할 때마다 `logs/hardware_log_YYYYMMDD_HHMMSS_ffffff.csv`를 생성하고 매 패킷 즉시 flush합니다. 주요 컬럼은 다음과 같습니다.

- 원본 수신 시각, packet ID/type, sequence, payload hex
- 기압 AGL 고도와 GPS 절대 고도
- GPS 위치, fix, 위성 수, HDOP, 속도, 진행 방향
- Low-G/High-G 가속도, 자이로, 기체 좌표계 변환 값
- pitch/roll/yaw, 배터리 전압, health/status, 비행 상태
- RSSI/SNR, 누락·중복·역순 프레임과 sequence reset 누계

시뮬레이션 데이터는 `logs/flight_log_*.csv`에 저장됩니다.

전체 런타임 상태:

```bash
curl http://127.0.0.1:8080/api/telemetry/status
```

터미널 패킷 모니터:

```bash
.venv/bin/python tools/monitor_packets.py \
  --port /dev/ttyACM1 --serial-mode raw
```

`raw` 모드에서는 인증 프레임과 `NURA_BRIDGE` 진단만 처리합니다. 레거시 수신기가 줄 단위 텍스트를 출력할 때만 `--serial-mode text`를 사용하십시오.

## API 요약

| Method | Endpoint | 용도 |
| --- | --- | --- |
| `GET` | `/` | Mission Control 화면 |
| `GET` | `/api/telemetry/next` | 최신 텔레메트리 |
| `POST` | `/api/telemetry/reset` | 로그/시뮬레이션 또는 항전 FSM reset |
| `GET` | `/api/telemetry/status` | 수신·프레임·브리지·로그 진단 |
| `GET` | `/api/flight/arm/status` | ARM 가능 여부와 차단 원인 |
| `POST` | `/api/flight/arm` | 인증된 `SAFE → ARMED` 명령 |
| `GET` | `/api/pyro/status` | 업링크와 PYRO 상태 |
| `POST` | `/api/pyro/deploy` | 인증된 PYRO 강제 전개 명령 |

## 프로젝트 구조

```text
GCS/
├── app.py                         # 최종 Flask 서버, 텔레메트리, API, CSV
├── mission_control.html           # 최종 웹 운용 UI
├── protocol.py                    # NURA V2 Lite 프레임/인증/페이로드
├── uplink.py                      # 시리얼 연결, 명령 생성, 재전송, ACK 판정
├── run_ground_station.sh          # Linux 하드웨어 원클릭 실행기
├── run_web_simulate.bat           # Windows 웹 시뮬레이션
├── run_web_hardware.bat           # Windows 하드웨어 웹 서버
├── desktop.py                     # 레거시 PyQt 보조 화면
├── firmware/lora_serial_bridge/   # Teensy 4.1 무선 브리지 펌웨어
├── tools/prepare_web_assets.py    # 브라우저 라이브러리 검증/캐시
├── tools/monitor_packets.py       # 현장 패킷 진단 CLI
├── logs/                          # 실행 중 생성되는 CSV 로그
└── test_*.py                      # 프로토콜·API·UI 계약 테스트
```

`gcs_integrated_server.py`는 기존 코드를 수정하지 않고 기능을 덧붙이던 이전 호환용 엔트리포인트입니다. 배터리와 하드웨어 로깅이 현재 `app.py`에 통합되어 있으므로 최종 운용은 `app.py` 또는 `run_ground_station.sh`를 사용하십시오.

## 테스트

```bash
.venv/bin/python -m unittest discover -v
```

테스트는 프레임 인증/파싱, 텔레메트리 흐름, 기체 축 변환, ARM 안전 게이트와 ACK 판정, UI/API 계약을 검증합니다. 하드웨어 연결과 실제 RF/PYRO 시험은 별도의 승인된 체크리스트로 수행해야 합니다.

## 오프라인 동작

`tools/prepare_web_assets.py`는 고정 SHA-256으로 검증한 Chart.js와 Leaflet을 `static/vendor/`에 캐시합니다. 이후 UI와 그래프는 인터넷 없이 열립니다. 지도 타일 영상은 선택한 온라인 타일 서버 연결이 있어야 표시되며, 연결이 없어도 수신·그래프·CSV 기록은 계속 동작합니다.

## License

라이선스 조건은 [`LICENSE`](LICENSE)를 참고하십시오.
