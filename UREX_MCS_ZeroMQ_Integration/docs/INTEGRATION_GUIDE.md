# MCS–Pi ZeroMQ統合指南書

## 完成している部分と実機への接続口

このブランチには、4タイプのProtobuf、UX＋CRC codec、ZeroMQ通信、MCS画面、コマンド追跡、CSV/JSONLログ、Python模擬Pi、C++ Piネットワークサービスが入っています。MQTT実装・比較ベンチマークは含みません。通常の `python main.py` は既存シミュレータを起動し、`--network` はPiからの情報だけを扱う画面を起動します。

**実機接続は未実施です。** Patrick/YuchengのC++コードをまだ受領していないため、RadioLib・SPI/GPIO・UARTを操作するコードは追加していません。C++ `Backend` の4メソッドが実機との接続口です。模擬Piの成功・RSSI/SNR・echoは合成値で、実機の動作確認ではありません。

GitHubの取得元は `Jutland3301/UREX_MCS_Prototype` の `v1.0`、基準commitは `5a7664146af0caaf6ee69387ec9c7864d8db0eb4`。既存 `schema/urex.proto` のフィールド番号は変更していません。統合用は独立した `schema/integration.proto` を使用します。UXフレームは共通ですが、旧 `UrexPacket` と統合用 `IntegrationPacket` は別の本体です。旧parserへ統合用パケットをそのまま渡さないでください。

## 確認したハードウェアの現状

10月8日に添付された「UREx meeting - updated.pptx」による構成です。

- Pi上のLinux C++アプリがRadioLib、SPI/GPIO、独立TX/RXワーカーを使用。
- LR2021(A)が送信、LR1121(B)が受信。受信payload、RSSI、SNRを取得。
- 現在の操作入口はESP32 UARTブリッジ、115200 baud、63バイトpayloadの行入力。
- 結果はUARTとSSH端末へ出力。SF変更は再build・再起動。
- 同じPi上のベンチリンクは確認済み。無線初期化の間欠的失敗と全二重動作は未解決／未検証。
- ベンチ設定は2445 MHz、BW 406.25 kHz、CR 4/7、TX −10 dBm。ネットワーク実装がこれらを勝手に変更することはありません。

63バイトは現在のUART入力経路に記載された上限です。SPIで直接RadioLibに渡す経路の最大値まで確認済みとは扱いません。初期値は63とし、実機adapterが実際に保証できる上限をStatusで通知してください。無線初期化に失敗している状態をREADYにしないでください。SDR/CAN/宇宙機について、このスライドから実機接続を確認できないため、模擬実装はUNAVAILABLEにしています。

## 1. 同じPCで確認する

リポジトリのルートで実行します。Windowsは `python3` を `python` に置き換えてください。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 main.py --network --bind "tcp://*:5557"
```

Windowsのvenv有効化は `.venv\Scripts\activate`。別ターミナルでも同じvenvを有効化して実行します。

```bash
python3 -m integration.mock_pi --connect tcp://127.0.0.1:5557
```

画面がCONNECTEDになり、PI/RADIOはREADY、他はUNAVAILABLE、ConfigurationにはMOCK ONLYと表示されます。Hexを選び `00 0A FF` を送信すると、コマンドはSENT→ACCEPTED→TX_COMPLETEDになり、Received payloadsに `000aff` が出ます。NUL・改行・0xFFを含む3バイトをそのまま往復できる確認です。MOCKのechoは宇宙機からの応答ではありません。

失敗と未応答は模擬Piを停止して次のどちらかで再起動します。

```bash
python3 -m integration.mock_pi --mode fail
python3 -m integration.mock_pi --mode timeout
```

failはFAILED、timeoutはACCEPTED後10秒でOUTCOME_UNKNOWNになります。自動再送はしません。模擬Piを停止すると最後のStatusから3秒でSTALEになり、送信ボタンが無効になります。再起動後は新sessionを検出し、未決コマンドを結果不明として残します。

MCSログは `logs/mcs` のCSVとJSONL（1行1JSON）。RX行にはPiイベント時刻とMCS側の受信時刻、payload hex、RSSI/SNRが入ります。未取得のRSSI/SNRは空欄です。`--log-dir` で保存先を変更できます。

## 2. C++側のネットワークサービスを確認する

Pi/Ubuntu側で必要な開発パッケージはg++、make、pkg-config、libzmq3-dev、libprotobuf-dev、protobuf-compilerです。依存ライブラリの導入はハードウェア担当の環境管理に合わせて行ってください。既存RadioLibアプリを変更する前に、独立したC++ mockを確認します。

```bash
make -C pi_service
./pi_service/build/mock_pi_cpp --connect tcp://127.0.0.1:5557
```

これはPython mockと同じschemaを使うC++サービスです。`--mode fail` / `--mode timeout` も指定できます。C++ mockは実機ドライバを一切呼びません。Protobuf C++ bindingsはPi側のprotocでbuild時に生成するため、protocとC++ runtimeは同じ環境のものを使用してください。

## 3. PCとPiをLANで接続する

MCS PCのLAN IPを確認し、MCSを `--network --bind "tcp://*:5557"` で起動します。Pi側の接続先を `tcp://<MCS-PCのIP>:5557` にします。必要ならPCのファイアウォールでこのLANからのTCP 5557を許可します。接続するPiは1台です。同じidentityで複数Piを同時接続すると競合するため、その構成は対象外です。

MCSはROUTERで待受け、PiはDEALERで接続します。Pi identityは `urex-pi`。DEALERが送るbodyはUXフレーム1個、ROUTERが受け取るmultipartは `[identity, UXフレーム]`。identityをCRC計算へ含めたり、REQ/REP用の空フレームを追加したりしないでください。ZeroMQの接続完了だけでREADYとは扱わず、実機からの有効なStatusを待ちます。

## 4. 既存C++ TX/RXワーカーへ接続する

`pi_service/backend.hpp` の `Backend` を既存アプリで実装し、`Service(endpoint, backend)` を作成します。既存のライフサイクルに合わせた1つのネットワークスレッドで `service.tick()` を10〜20msごとに呼びます。socketの生成・tick・破棄は同じスレッドで行ってください。TX/RXスレッドからsocketを直接呼ばず、mutex等で保護したqueueでイベントを受け渡します。

| メソッド | 接続する実処理 |
|---|---|
| `snapshot()` | Pi・無線等の実際の初期化状態、エラー、保証できるTX payload上限を返す。毎秒と変更時に通知される。未接続の機器はUNAVAILABLE。 |
| `submit_transmit(id, bytes)` | command IDと正確なバイト列を既存TX queueへ積む。ネットワークスレッドで無線送信を待たない。 |
| `drain_completions()` | TXワーカーが生成したcommand ID、成功/失敗、実イベント時刻、エラーを回収する。 |
| `drain_received()` | RXワーカーのpayload、Pi取得時刻、任意のRSSI/SNR/CRC結果を回収する。 |

`std::string` はここではバイナリ容器です。送信は必ず `data()` と `size()` を使い、`strlen()`や改行終端に依存しないでください。MCSは完成したradio payloadを渡します。Piが別の高レベルコマンドからpayloadを構成する方式ではありません。

ESP32 UART入口を維持する場合は、ZeroMQ入口と同じTX queueに接続し、無線機への同時アクセスをワーカー側で直列化します。UARTからのローカル送信を、無関係なMCS command IDの完了として報告しないでください。RX情報はネットワークへ報告できます。

**TX_COMPLETEDはRadioLibの送信完了を取得してから報告します。** queueへの投入やUART writeの完了だけでは送信完了にしません。現在のコードで完了を取得できない場合はTX_CONFIRMATION_UNAVAILABLEを報告し、接続方法を担当者と確認するところで止めてください。実機で継続中かもしれない送信を単なる応答時間超過でFAILEDにしないでください。

RX時刻はPiがhardware interfaceから完全なpayloadを取得したUTC Unixミリ秒。宇宙機送信時刻やRF到着時刻ではありません。RadioLibがCRC失敗フレームを破棄する場合、CRC結果が不明ならフィールドを省略します。CRC失敗を通常の成功RXとして送らないでください。クロック同期が確認できない限りclock_synchronized=falseとし、PC–Pi間の片道遅延を断定しないでください。

## 5. 実機接続前に確認が必要な事項

現在のC++コード受領時に以下を確認し、分からない箇所は推測で接続しないでください。

1. TX queueのAPI・buffer寿命・送信完了通知の取得位置とエラー値。
2. 直接RadioLibへ渡すpayload上限と、NUL/改行を含むバイナリ送信への対応。
3. RX payload長・RSSI/SNRの取得API・CRC失敗時の動作。
4. 初期化失敗／再初期化の状態変化と、既存TX/RXワーカーの排他制御。
5. Piの実際の時計同期と、PC–Pi間のIP・ポート到達性。

## 6. 実機統合の確認順

まずPi上のC++ mockでPCとのネットワークを確認します。次に実機backendへ差し替えてStatusだけを確認し、無線が未初期化なら送信不可であることを確認します。既存ベンチで使用している設定・テスト用payloadで1回の送信要求を試し、command IDに対応した実際の完了を確認します。その後、受信payload・RSSI/SNR・時刻を既存SSH/UARTログと照合します。

最後に同じcommand IDの重複要求で無線送信が増えないこと、payload上限超過、初期化失敗、ネットワーク切断、Pi再起動を確認します。無線全二重動作の成功はネットワークの成功とは別に測定します。模擬Piのecho、MCSが受信したcommand result、ZeroMQの接続成功を、宇宙機受信の証拠にしないでください。

仕様の詳細とshared HEX test vectorは [MCS_PI_INTERFACE.md](MCS_PI_INTERFACE.md)、schemaは `schema/integration.proto` にあります。
