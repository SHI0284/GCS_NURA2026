# 에비오닉스 에이전트 인계: GCS 명령 기반 SAFE -> ARMED

## 목표와 변경 경계

GCS는 인증된 업링크 명령 `ARM_FLIGHT(0x04)`를 구현했다. 에비오닉스에서는
production flight FSM의 자동 `SAFE -> ARMED` 전이를 제거하고, 이 명령을 정상
수신·검증·수락한 경우에만 FSM task가 `ARMED`로 전이하도록 구현한다.

중요한 안전 경계:

- telemetry/radio task에서 `flightState_.state = State::ARMED`로 직접 대입하지 않는다.
- 요청은 공유 상태에 큐잉하고 실제 전이는 `FlightStateMachineTask`만 수행한다.
- abort가 active이거나 현재 상태가 정확히 `SAFE`가 아니면 거부한다.
- ARM 명령은 파이로 출력을 켜는 명령이 아니다. 기존 출력 inhibit와 연속성/센서/abort
  안전 조건을 완화하지 않는다.
- `ACK_EXECUTED`는 FSM 전이와 `onEnter(State::ARMED)`가 끝나 현재 상태 코드가 실제
  `FLIGHT_ARMED(2)`일 때만 보낸다.

## 확정된 wire contract

NURA V2 Lite CONTROL payload는 기존과 동일한 고정 24바이트이며 새 바이트를 늘리지
않는다. 기존 `param0`, `param1` 공간을 상태 전이 계약으로 사용한다.

| CONTROL offset | 길이 | ARM 값 | 의미 |
| ---: | ---: | ---: | --- |
| 0 | 1 | `0x01` | `CONTROL_CMD` |
| 1 | 1 | `0x04` | `COMMAND_ARM_FLIGHT` |
| 2 | 2 | 가변 LE | `commandSeq` |
| 4 | 4 | 가변 LE | `nonce` |
| 8 | 4 | 0이 아닌 LE | avionics `millis()` 기준 `validUntilMs` |
| 12 | 2 | `1` LE signed | 예상 출발 상태 `FLIGHT_SAFE` |
| 14 | 2 | `2` LE signed | 요청 목표 상태 `FLIGHT_ARMED` |
| 16 | 8 | 가변 | 기존 `makeControlAuthTag` 결과 |

전체 프레임은 기존과 같은 43바이트다: 9-byte header + 24-byte CONTROL + 8-byte
frame auth + 2-byte CRC. 방향은 `UPLINK(0x55)`이다. `validUntilMs=0`은 ARM에 한해
반드시 `RESULT_BAD_FORMAT`으로 거부한다. GCS는 최신 FAST의 `boot_ms`를 host 경과
시간으로 보정한 뒤 3000 ms를 더해 만료 시각을 만든다.

공개 bench key/vehicle ID를 이용한 상호운용 테스트 벡터:

```text
frame_seq     = 0x1234
command_seq   = 0x3344
nonce         = 0xA1B2C3D4
validUntilMs  = 54321

CONTROL payload:
01 04 44 33 d4 c3 b2 a1 31 d4 00 00 01 00 02 00
cf 9d 6d 96 41 a0 11 0a

full uplink frame:
aa 55 23 41 52 55 4e 34 12 01 04 44 33 d4 c3 b2
a1 31 d4 00 00 01 00 02 00 cf 9d 6d 96 41 a0 11
0a 13 d5 1b 51 d9 de 6e cd d2 3d
```

## 에비오닉스 구현 요구 사항

1. `protocol/include/nura_protocol_v1_lite.h`
   - `CommandId`에 `COMMAND_ARM_FLIGHT = 0x04U`를 추가한다.
   - 기존 24바이트 encode/decode, control auth 입력, frame auth/CRC는 변경하지 않는다.

2. `src/state/flight_state.h`
   - 기존 force-deploy/reset 요청 패턴처럼 ARM 요청/실행 상태와 seq를 추가한다.
   - 예: `armRequested`, `armRequestSeq`, `armExecuted`, `armExecutedSeq`.

3. `src/missions/telemetry/telemetry_task.{h,cpp}`
   - `handleCommand()`에 `COMMAND_ARM_FLIGHT` case를 추가한다.
   - 공통 auth, expiry, recent-command 검사가 끝난 다음 아래를 모두 검사한다.
     - `validUntilMs != 0`
     - `param0 == FLIGHT_SAFE`, `param1 == FLIGHT_ARMED`
     - `flightState_.state == State::SAFE`
     - `abortState_.status.active == false`
     - 다른 reset/ARM 요청과 충돌하지 않음
   - format 오류는 `ACK_REJECTED / RESULT_BAD_FORMAT`으로, 상태/abort 오류는
     `ACK_REJECTED / RESULT_BAD_STATE / REJECT_STATE_REJECTED`로 답한다.
   - 통과하면 요청 flag/seq와 별도의 `pendingArmAck_`를 저장하고
     `ACK_ACCEPTED / RESULT_OK`를 보낸 뒤 `rememberCommand()` 한다.
   - `enqueueDeferredCommandAcks()`에서 FSM이 같은 seq의 실행 완료를 기록했고 현재
     상태가 `State::ARMED`일 때만 `ACK_EXECUTED / RESULT_OK`를 큐잉한다.
   - 동일 프레임 재전송에는 기존 recent-command 로직으로 `ACK_DUPLICATE`를 보내되,
     원래 pending ARM의 추후 `ACK_EXECUTED`를 지우지 않는다.

4. `src/missions/flight/fsm_task.{h,cpp}`
   - 일반 production 경로의 현재 코드는 `case State::SAFE`에서 abort가 아니면 곧바로
     `State::ARMED`로 전이한다. 이 자동 전이를 제거한다.
   - bench 전용 `NURA_BENCH_FSM_AUTOFLOW`, serial step 기능은 해당 build flag 안에서만
     기존 동작을 유지할 수 있다.
   - `consumeArmRequest(nowMs)` 같은 FSM 소유 함수를 만들고, 요청이 있으며 현재
     `SAFE`, abort inactive인 경우에만 `transitionTo(State::ARMED, nowMs)`를 호출한다.
   - 전이가 끝난 뒤에만 요청 flag를 내리고 `armExecuted=true`, 실행 seq를 기록한다.
   - 전이 직전 abort가 active로 바뀐 race에서는 요청을 실행하지 않고 SAFE를 유지한다.

5. LoRa RX 활성화
   - 사용자가 요청한 대로 대상 flight build에서 `kFlightDownlinkOnly=false`가 실제로
     컴파일되게 한다. 전처리기 양쪽 값이 섞여 GCS가 빌드를 추정하게 두지 말고,
     production build 의도를 명시적으로 드러낸다.
   - 송신 후 RX 복귀, CONTROL 수신, FAST/GPS 주기 유지, watchdog timing을 검증한다.

## 필수 테스트

- production FSM은 INIT -> SAFE 뒤 명령 없이 계속 SAFE에 머문다.
- 올바른 ARM 프레임은 `ACCEPTED(SAFE)` 후 FSM 전이 뒤
  `EXECUTED/OK(ARMED=2)` 순서로 응답한다.
- auth 오류, CRC 오류, 만료, `validUntilMs=0`, 잘못된 params를 각각 거부한다.
- INIT/ARMED/LAUNCH/FAULT/GROUND 등 SAFE 이외 모든 상태에서 거부한다.
- abort active와 ARM 수신 race에서 SAFE를 유지하고 거부/미실행 처리한다.
- 같은 `(commandId, commandSeq, nonce)` 재전송은 재실행하지 않는다.
- ACK 유실 후 같은 프레임을 250 ms 간격으로 8회 받아도 전이는 한 번뿐이다.
- ARM 처리만으로 drogue/main pyro GPIO가 energize되지 않음을 fake HAL/trace로 검증한다.
- 위 golden vector가 C++ decoder와 control-auth 검증을 통과한다.
- `main`, `debug` 대상 빌드와 기존 FSM replay/protocol tests를 모두 통과시킨다.

## GCS 쪽 완료 계약

- 구현 파일: `protocol.py`, `uplink.py`, `app.py`, `mission_control.html`
- 상태 API: `GET /api/flight/arm/status`
- 명령 API: `POST /api/flight/arm` with
  `{"confirm":"ARM","expected_state":1}`
- 하드웨어 ARM 조건: raw bridge 연결, provisioned radio identity, downlink-only 해제,
  radio init 정상, 1.5초 이내 인증 FAST, 최신 상태 SAFE.
- GCS 성공 조건: `ACK_EXECUTED`, `RESULT_OK`, ACK의 flight state byte가 `2`.

## 에이전트에게 그대로 전달할 요청문

```text
GCS의 AVIONICS_ARM_UPLINK_HANDOFF_KR.md 계약대로 에비오닉스만 수정해라.
COMMAND_ARM_FLIGHT=0x04를 추가하고 param0=SAFE(1), param1=ARMED(2), non-zero
validUntilMs를 검증해라. production FSM의 자동 SAFE->ARMED를 제거하고, 인증된 ARM
요청을 telemetry task가 큐잉한 뒤 FlightStateMachineTask만 전이를 수행하게 해라.
abort active 또는 SAFE 이외 상태에서는 fail-closed로 거부하고, ACK_ACCEPTED는 요청
수락 시, ACK_EXECUTED/OK는 실제 상태가 ARMED(2)가 된 뒤에만 보내라. 중복 프레임은
재실행하지 말고 pending EXECUTED ACK는 유지해라. ARM 처리에서 pyro 출력은 절대
energize하지 마라. 대상 flight build의 downlinkOnly도 실제 false로 만들고 RX 복귀와
telemetry cadence를 검증해라. 문서의 golden vector 및 모든 거부/중복/abort race/FSM
replay 테스트를 추가한 뒤 main/debug 빌드 결과와 변경 파일을 보고해라.
```
