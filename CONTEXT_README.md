Наша библиотека `sip_simulator` должна представлять собой Python SDK для автоматизированной эмуляции SIP-звонков, построенный на PJSIP/PJSUA2.

Главный архитектурный принцип: пользователь библиотеки не должен знать о существовании PJSUA2. Он работает с `SipClient`, `CallSession` и моделями Pydantic. Всё взаимодействие с нативной SIP-библиотекой изолируется внутри `adapters/`.

Ниже опишу архитектуру, жизненный цикл вызовов, API адаптеров и основные технические решения.

## 1. Общие принципы работы библиотеки

```
Пользователь / pytest (Создание вызова, отправка аудио, проверки)
    ↓
client.py (Публичный API библиотеки) 
    ↓
core/ (SipEngine · CallManager · CallSession · EventDispatcher) 
    ↓
adapters/ (Контракты и реализация PJSIP) 
    ↓
PJSUA2 → SIP / RTP → Asterisk или Kamailio
```

### Разделение ответственности

| Компонент          | За что отвечает                             |
| ------------------ | ------------------------------------------- |
| `SipClient`        | Предоставляет удобный API пользователю      |
| `SipEngine`        | Управляет жизненным циклом SIP-движка       |
| `CallManager`      | Создаёт и отслеживает звонки                |
| `CallSession`      | Управляет конкретным вызовом                |
| `EventDispatcher`  | Распространяет события SIP                  |
| `media/`           | Воспроизведение, запись и конвертация аудио |
| `model/`           | Pydantic-модели данных                      |
| `adapters/base.py` | Контракты для SIP-бэкендов                  |
| `adapters/pjsip/`  | Реализация контрактов через PJSUA2          |

Принцип зависимости:

```
client → core → adapters.base
                    ↑
              adapters.pjsip
```

`core/` не импортирует `pjsua2`, а работает только с интерфейсами.

## 2. Жизненный цикл библиотеки

Предположим, что пользователь пишет:

```python
from sip_simulator import SipClient, SipConfig

config = SipConfig(
    host="127.0.0.1",
    username="1000",
    password="test123",
)

with SipClient(config) as client:
    call = client.call("1001")

    call.wait_for_answer(timeout=15)
    call.wait_for_media(timeout=10)

    call.play_audio("audio/hello.wav")
    call.hangup()
```

Это целевой API, к которому мы стремимся.

### Этап 1. Инициализация

`SipClient.start()` вызывает `SipEngine.start()`.

Движок делегирует создание PJSUA2 Endpoint адаптеру:

```
SipEngine.start()
    ↓
PjsipEndpoint.start()
    ↓
pj.Endpoint()
    ↓
libCreate()
    ↓
libInit()
    ↓
transportCreate()
    ↓
libStart()
```

После запуска создаётся SIP-аккаунт через `PjsipAccount`.

Если `register_account=True`, адаптер инициирует SIP REGISTER и ожидает события регистрации.

### Этап 2. Создание звонка

```
SipClient.call("1001")
    ↓
CallManager.create_call()
    ↓
PjsipAccount.create_call()
    ↓
PjsipCall.make_call()
    ↓
PJSUA2 makeCall()
    ↓
SIP INVITE
```

Здесь важно различать два идентификатора:

- `call_info_id` — UUID нашей библиотеки, используемый для поиска сессии.
- `callId` PJSIP — внутренний идентификатор вызова, который управляется нативной библиотекой.

В публичном API используем только `call_info_id`.

### Этап 3. Обработка событий

PJSUA2 уведомляет о состоянии звонка через callback:

```python
def onCallState(self, prm):
    ...
```

Наш адаптер преобразует данные PJSIP в `CallStateChangedEvent` и отправляет событие в `EventDispatcher`.

```
PJSUA2 callback
    ↓
PjsipCall.onCallState()
    ↓
CallStateChangedEvent
    ↓
EventDispatcher.publish()
    ↓
CallSession обновляет CallInfo
    ↓
wait_for_answer() разблокируется
```

### Этап 4. Передача аудио

После установления соединения PJSUA2 сообщает о готовности медиапотока.

`CallSession.play_audio()` обращается к `AudioPlayer`, который подключает `pj.AudioMediaPlayer` к `pj.AudioMedia` звонка.

Важно: SIP устанавливает сеанс, а само аудио передаётся по RTP.

### Этап 5. Завершение

При вызове `call.hangup()`:

1. `CallSession` обращается к адаптеру.
2. PJSUA2 отправляет SIP BYE, если вызов уже установлен.
3. Приходит событие `DISCONNECTED`.
4. `CallManager` удаляет вызов из активного реестра.
5. Медиаобъекты освобождаются.
6. При `SipClient.stop()` уничтожаются аккаунты и Endpoint.

Не следует уничтожать объект `pj.Call` сразу после `hangup()`: завершение вызова асинхронно.

# 3. `adapters/base.py` — контракты

Я предлагаю использовать `typing.Protocol`, а не абстрактные базовые классы.

Это позволит тестировать `core/` с помощью простых fake-объектов без наследования.

Главные интерфейсы:

- `EndpointBackend` — жизненный цикл SIP-движка.
- `AccountBackend` — регистрация и создание звонков.
- `CallBackend` — управление конкретным звонком.
- `SipBackendFactory` — создание реализаций.

## Предлагаемый API `base.py`

```python

from collections.abc import Callable
from typing import Protocol

from sip_simulator.config import SipConfig
from sip_simulator.model.call_info import CallInfo


class CallBackend(Protocol):
    @property
    def call_info_id(self) -> str:
        ...

    def make_call(self, destination_uri: str) -> None:
        ...

    def answer(self, status_code: int = 200) -> None:
        ...

    def hangup(self, status_code: int = 0) -> None:
        ...

    def send_dtmf(self, digits: str) -> None:
        ...

    def get_info(self) -> CallInfo:
        ...

    def close(self) -> None:
        ...


class AccountBackend(Protocol):
    def register(self) -> None:
        ...

    def unregister(self) -> None:
        ...

    def create_call(self, call_info_id: str) -> CallBackend:
        ...

    def close(self) -> None:
        ...


class EndpointBackend(Protocol):
    def start(self) -> None:
        ...

    def poll(self, timeout_ms: int = 50) -> int:
        ...

    def stop(self) -> None:
        ...


class SipBackendFactory(Protocol):
    def create_endpoint(
        self,
        config: SipConfig,
    ) -> EndpointBackend:
        ...

    def create_account(
        self,
        endpoint: EndpointBackend,
        config: SipConfig,
    ) -> AccountBackend:
        ...

```

Это проектируемый контракт, который нужно согласовать с уже написанными `core/` и `client.py`, а не готовая drop-in-замена их текущих интерфейсов.

Важный момент: в данном варианте `CallBackend` создаётся аккаунтом. Поэтому отдельная фабрика вызовов в `SipClient` становится необязательной.

Также здесь пока не отражён механизм передачи событий. Я бы сделал его отдельной зависимостью, чтобы `base.py` не связывался с конкретной реализацией диспетчера.

Например, адаптеры могут получать:

```python
EventSink = Callable[[SipEvent], None]
```

где `SipEvent` — объединение Pydantic-моделей событий из `core/events.py`.

# 4. `adapters/pjsip/endpoint.py`

## Назначение

`PjsipEndpoint` — оболочка над `pj.Endpoint`.

Он отвечает за:

- Создание PJSUA2 Endpoint.
- Инициализацию SIP-стека.
- Создание UDP/TCP/TLS-транспорта.
- Запуск движка.
- Обработку событий.
- Корректное освобождение ресурсов.

### Публичный API

```python
class PjsipEndpoint:
    def __init__(self, config: SipConfig) -> None:
        ...

    def start(self) -> None:
        ...

    def poll(self, timeout_ms: int = 50) -> int:
        ...

    def stop(self) -> None:
        ...

    @property
    def is_running(self) -> bool:
        ...
```

### Что происходит внутри `start()`

```python
self._endpoint = pj.Endpoint()
self._endpoint.libCreate()

ep_config = pj.EpConfig()
ep_config.uaConfig.threadCnt = 0

self._endpoint.libInit(ep_config)

transport_config = pj.TransportConfig()
transport_config.port = self._config.local_port

self._endpoint.transportCreate(
    pj.PJSIP_TRANSPORT_UDP,
    transport_config,
)

self._endpoint.libStart()
```

Это упрощённый пример для UDP, не полная реализация. В настоящем адаптере необходимо предусмотреть обработку частично успешной инициализации, настройки кодеков и особенности работы потоков.

Для Python я бы дополнительно установил:

```python
ep_config.uaConfig.mainThreadOnly = True
```

Вместе с `threadCnt=0` это позволяет организовать обработку событий в контролируемом потоке через `libHandleEvents()`.

При этом все операции с PJSUA2 должны выполняться с учётом его требований к регистрации потоков и жизненному циклу объектов.

### Метод `poll()`

```python
def poll(self, timeout_ms: int = 50) -> int:
    if not self.is_running:
        raise RuntimeError("PJSIP endpoint is not running")

    return self._endpoint.libHandleEvents(timeout_ms)
```

`poll()` особенно важен: если мы используем ручную обработку событий, то при ожидании звонка необходимо регулярно вызывать этот метод.

Поэтому `CallSession.wait_for_answer()` должен либо сам обеспечивать обработку событий через переданный механизм, либо полагаться на отдельный управляющий цикл, который их обрабатывает.

Нельзя просто вызвать `threading.Event.wait(15)` в единственном потоке, который должен выполнять `libHandleEvents()`.

### Логирование

```
logger = logging.getLogger(__name__)
```

Основные события:

```
INFO  PJSIP endpoint initialization started
INFO  SIP transport created protocol=udp port=5060
INFO  PJSIP endpoint started
DEBUG PJSIP events processed count=2
INFO  PJSIP endpoint stopped
ERROR Failed to initialize PJSIP endpoint
```

`poll()` лучше логировать на `DEBUG` только при наличии событий, иначе журнал быстро разрастётся.

# 5. `adapters/pjsip/account.py`

## Назначение

`PjsipAccount` — реализация SIP-аккаунта через наследование от `pj.Account`.

Он отвечает за:

- Создание SIP-аккаунта.
- Регистрацию на сервере.
- Получение статуса регистрации.
- Приём входящих вызовов.
- Создание исходящих вызовов.

### Предлагаемый API

```python
class PjsipAccount(pj.Account):
    def __init__(
        self,
        config: SipConfig,
        event_sink: EventSink,
    ) -> None:
        ...

    def start(self) -> None:
        ...

    def register(self) -> None:
        ...

    def unregister(self) -> None:
        ...

    def create_call(
        self,
        call_info_id: str,
    ) -> CallBackend:
        ...

    def onRegState(self, prm) -> None:
        ...

    def onIncomingCall(self, prm) -> None:
        ...

    def close(self) -> None:
        ...
```

В отличие от `base.py`, этот класс уже зависит от PJSUA2.

### Регистрация аккаунта

При создании аккаунта формируем `pj.AccountConfig`:

```python
account_config = pj.AccountConfig()

account_config.idUri = "sip:1000@127.0.0.1"
account_config.regConfig.registrarUri = "sip:127.0.0.1"

credentials = pj.AuthCredInfo(
    "digest",
    "*",
    "1000",
    0,
    "test123",
)

account_config.sipConfig.authCreds.append(credentials)

self.create(account_config)
```

В рабочей реализации URI, имя пользователя и пароль берутся из `SipConfig`.

В PJSUA2 метод `create()` создаёт аккаунт и при включённой регистрации обычно инициирует REGISTER. Поэтому `register()` не должен повторно отправлять регистрацию без необходимости. Для явного управления используется `setRegistration(True/False)`.

### Callback регистрации

```python
def onRegState(self, prm):
    info = self.getInfo()

    logger.info(
        "SIP registration changed: code=%s",
        info.regStatus,
    )

    # Преобразовать статус в Pydantic-модель
    # и отправить событие в EventDispatcher.
```

Необходимо учитывать, что `onRegState()` может вызываться несколько раз за жизненный цикл аккаунта, в том числе при повторной регистрации.

### Входящие звонки

При поступлении `onIncomingCall()` PJSUA2 предоставляет идентификатор нового вызова.

Адаптер должен создать `PjsipCall` с этим нативным ID и сохранить ссылку на объект.

Важно, чтобы событие о входящем звонке содержало достаточно информации для создания `CallSession`, но не передавало наружу сам объект `pj.Call`.

# 6. `adapters/pjsip/call.py`

Это самый важный адаптер, потому что он связывает SIP-сигнализацию с `CallSession` и `media/`.

## Назначение

`PjsipCall` наследуется от `pj.Call` и отвечает за:

- Создание исходящих вызовов.
- Приём входящих.
- Отправку SIP-ответов.
- Завершение звонков.
- DTMF.
- Отслеживание SIP-состояний.
- Получение аудиомедиа.
- Публикацию событий.

### Предлагаемый API

```python
class PjsipCall(pj.Call):
    def __init__(
        self,
        account: pj.Account,
        call_info_id: str,
        event_sink: EventSink,
        call_id: int = pj.PJSUA_INVALID_ID,
    ) -> None:
        ...

    def make_call(self, destination_uri: str) -> None:
        ...

    def answer(self, status_code: int = 200) -> None:
        ...

    def hangup(self, status_code: int = 0) -> None:
        ...

    def send_dtmf(self, digits: str) -> None:
        ...

    def get_info(self) -> CallInfo:
        ...

    def get_audio_media(self):
        ...

    def onCallState(self, prm) -> None:
        ...

    def onCallMediaState(self, prm) -> None:
        ...

    def close(self) -> None:
        ...
```

### Исходящий звонок

```python
def make_call(self, destination_uri: str) -> None:
    prm = pj.CallOpParam(True)
    self.makeCall(destination_uri, prm)
```

Этот вызов инициирует SIP INVITE, но не означает, что звонок уже установлен.

### Завершение

```python
def hangup(self, status_code: int = 0) -> None:
    prm = pj.CallOpParam()
    prm.statusCode = status_code
    self.hangup(prm)
```

Здесь есть важная проблема проектирования: метод Python-обёртки называется так же, как метод PJSUA2. Если написать `self.hangup(prm)`, получится рекурсивный вызов нашего метода.

Поэтому реализация должна явно вызывать базовый метод:

```python
pj.Call.hangup(self, prm)
```

Аналогично для других методов, имена которых могут пересекаться.

Я бы даже переименовал публичный метод адаптера в `terminate()`, чтобы избежать таких конфликтов. В `CallSession` при этом можно оставить привычный `hangup()`.

### Обработка состояний

PJSUA2 имеет более подробные состояния вызова, чем наш `CallState`.

Нужен mapper:

| PJSUA2                         | Наш `CallState`              |
| ------------------------------ | ---------------------------- |
| `PJSIP_INV_STATE_NULL`         | `IDLE`                       |
| `PJSIP_INV_STATE_CALLING`      | `CALLING`                    |
| `PJSIP_INV_STATE_INCOMING`     | `RINGING`                    |
| `PJSIP_INV_STATE_EARLY`        | `RINGING`                    |
| `PJSIP_INV_STATE_CONNECTING`   | `CALLING`                    |
| `PJSIP_INV_STATE_CONFIRMED`    | `CONNECTED`                  |
| `PJSIP_INV_STATE_DISCONNECTED` | `DISCONNECTED` либо `FAILED` |

`FAILED` лучше определять не только по нативному состоянию, но и по SIP-коду и контексту вызова. Например, исходящий вызов, отклонённый с `486 Busy Here`, не должен ошибочно считаться успешно завершённым.

### Получение аудиомедиа

В `onCallMediaState()` адаптер проверяет, какие медиапотоки активны.

Для аудиопотока можно получить объект через `getAudioMedia(media_index)`.

Дальше `AudioPlayer` подключает WAV:

```
player.startTransmit(call_audio_media)
```

При этом аудиомедиа нельзя считать готовым только потому, что звонок перешёл в `CONNECTED`. Нужно дождаться отдельного события о состоянии медиа.

# 7. Как должны взаимодействовать `events.py` и адаптеры

Я бы использовал следующую схему:

```
PJSUA2 callback
    ↓
PjsipCall / PjsipAccount
    ↓
Pydantic Event
    ↓
EventSink
    ↓
EventDispatcher
    ↓
CallSession / CallManager
```

Адаптеру не нужно знать, кто именно подписан на события.

Например:

```
def onCallState(self, prm):    info = self.getInfo()    event = CallStateChangedEvent(        call_info_id=self._call_info_id,        state=map_call_state(info.state),        sip_status_code=info.lastStatusCode,        sip_reason=info.lastReason,    )    self._event_sink(event)
```

Названия полей здесь должны соответствовать реальным Pydantic-моделям в `core/events.py`.

Все события должны содержать идентификатор звонка, время возникновения и тип события. Для отладки особенно полезно логировать SIP-код, направление вызова и предыдущий/новый статус.

## 8. Важные технические решения

| Вопрос           | Решение                                                        |
| ---------------- | -------------------------------------------------------------- |
| Pydantic         | Для конфигураций, событий и снимков состояния                  |
| Логирование      | `logging.getLogger(__name__)` во всех компонентах              |
| Нативные объекты | Только внутри `adapters/pjsip/` и инфраструктурного media-слоя |
| Потоки           | Один контролируемый поток PJSIP на первом этапе                |
| События          | Через `EventSink` и `EventDispatcher`                          |
| Идентификаторы   | UUID библиотеки отдельно от PJSIP callId                       |
| Ошибки           | Собственные исключения SDK                                     |
| Тестирование     | Fake-адаптеры для unit-тестов, Asterisk для интеграционных     |
| Завершение       | Сначала вызовы, затем аккаунты, затем Endpoint                 |

Особенно важно соблюдать порядок уничтожения объектов. Python-сборщик мусора не всегда обеспечивает подходящий момент освобождения C++-объектов PJSUA2.

## 9. Рекомендованный итоговый API

Я бы зафиксировал следующие основные операции:

```python
# Endpoint
endpoint.start()
endpoint.poll(timeout_ms=50)
endpoint.stop()

# Account
account.register()
account.unregister()
account.create_call(call_info_id)
account.close()

# Call
call.make_call(destination_uri)
call.answer(status_code=200)
call.terminate()
call.send_dtmf("123")
call.get_info()
call.get_audio_media()
call.close()
```

И две обязательные границы ответственности:

`core/` отвечает на вопрос «что должно произойти?», например создать звонок, дождаться ответа, завершить сессию.

`adapters/pjsip/` отвечает на вопрос «как выполнить это через PJSUA2?», включая конкретные вызовы C++-биндингов, обработку callback'ов и преобразование SIP-состояний.

Такой подход даст возможность развивать библиотеку без превращения `client.py` или `call_session.py` в огромные классы, напрямую работающие с PJSIP.

Следующим шагом разумно сначала окончательно согласовать `adapters/base.py` с существующим `core/`, а затем реализовать три PJSIP-адаптера. Это позволит избежать несовместимых сигнатур и переделки уже написанных компонентов.