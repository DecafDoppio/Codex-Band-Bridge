wit_bindgen::generate!({ path: "wit", world: "psys-world-v4-http", generate_all });

use astrobox::psys_host_v4::{
    device, http_server, interconnect, os, register, timer, ui, thirdpartyapp, clipboard, dialog,
};
use bridge_core::{Bridge, NewRequest, decode_interconnect_event};
use bridge_core::launch::LaunchDelivery;
use std::collections::BTreeSet;
use exports::astrobox::psys_plugin_v4::{event, http, lifecycle};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};
mod dashboard_ui;
mod hook_commands;
use bridge_core::dashboard::{Facts, Issue, stages};

const PACKAGE: &str = "com.local.codexband";
const CONFIG_FILE: &str = "settings.json";
// System notification send/remove remain absent in Scheme B.
const VERSION: &str = env!("CARGO_PKG_VERSION");

// Record structure only: no text, credentials, ticket values or arbitrary keys.
fn frame_shape(value: &Value, depth: usize) -> Value {
    let kind = match value {Value::Null=>"null",Value::Bool(_)=>"boolean",Value::Number(_)=>"number",Value::String(_)=>"string",Value::Array(_)=>"array",Value::Object(_)=>"object"};
    let mut shape=json!({"kind":kind});
    if depth>=2 {return shape;}
    if let Some(object)=value.as_object() {
        let mut fields=serde_json::Map::new();
        for key in ["v","type","data","payload","message","content","method","params","id","ticket","firmware","visible"] {
            if let Some(child)=object.get(key) {fields.insert(key.into(),frame_shape(child,depth+1));}
        }
        if depth<2 {shape["fields"]=Value::Object(fields);}
        shape["fieldCount"]=json!(object.len());
        // Protocol identifiers only; cap size and reject text-like/non-ASCII keys.
        shape["keyTypes"]=json!(object.iter().take(16).filter_map(|(key,child)| {
            let mut chars=key.chars();
            let first=chars.next()?;
            if key.len()>32 || !(first.is_ascii_alphabetic() || first=='_') || !chars.all(|c|c.is_ascii_alphanumeric() || c=='_') {return None;}
            let kind=match child {Value::Null=>"null",Value::Bool(_)=>"boolean",Value::Number(_)=>"number",Value::String(_)=>"string",Value::Array(_)=>"array",Value::Object(_)=>"object"};
            Some(json!({"key":key,"kind":kind}))
        }).collect::<Vec<_>>());
        shape["v1"]=json!(object.get("v").and_then(Value::as_u64)==Some(1));
            if let Some(command)=object.get("type").and_then(Value::as_str) {
            shape["knownCommand"]=json!(matches!(command,"hello"|"list"|"ping"|"detail"|"decision"|"stop"|"resume"|"binding"));
        }
    } else if depth<2 {
        if let Some(text)=value.as_str() {
            if let Ok(inner)=serde_json::from_str::<Value>(text) {shape["jsonShape"]=frame_shape(&inner,depth+1);}
        }
    }
    shape
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
struct Config {
    enabled: bool,
    device_addr: String,
    port: u16,
    token: String,
    host_id: String,
    wake_app: bool,
    scheme_b_enabled: bool,
    hooks_config_ready: bool,
    hooks_initial_start_done: bool,
    hooks_install_command_version: String,
    hooks_config_version: String,
    hooks_checked_at: u64,
    hooks_forwarding_paused: bool,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            enabled: false,
            device_addr: String::new(),
            port: 37121,
            token: String::new(),
            host_id: String::new(),
            wake_app: false,
            scheme_b_enabled:false,
            hooks_install_command_version:String::new(),hooks_initial_start_done:false,hooks_config_ready:false,hooks_config_version:String::new(),hooks_checked_at:0,hooks_forwarding_paused:false,
        }
    }
}
struct App {
    selected_stage: Option<String>,
    manual_selection: bool,
    diagnostics: bool,
    render_width: u32,
    ui_notice: String,
    power_rejected: bool,
    issue: Option<Issue>,
    setup_epoch: String,
    setup_state: String,
    setup_checked_at: u64,
    setup_forwarding_paused: bool,
    resume_requested: bool,
    diagnostic_kind: String,
    diagnostic_deadline: u64,
    diagnostic_done_at: u64,
    test_passed: bool,
    last_render_signature: String,
    config: Config,
    saved_config: Option<Config>,
    bridge: Bridge,
    server_id: Option<u32>,
    tick: Option<u64>,
    devices: Vec<(String, String)>,
    known_devices: Vec<(String, String)>,
    subscribed: String,
    registration_pending: bool,
    registration_failed: bool,
    ui_id: String,
    error: String,
    probe_last: Value,
    delivery: LaunchDelivery,
    probe_pending: bool,
    reconnect_attempts: usize,
    reconnect_at: u64,
    launch_validated: bool,
    launch_status: String,
    watch_visible: bool,
    watch_seen: u64,
    watch_rx_count: u64,
    watch_rx_kind: String,
    watch_reply_error: String,
    watch_rx_shape: Value,
}
impl Default for App {
    fn default() -> Self {
        Self {
            power_rejected:false,selected_stage:None,manual_selection:false,diagnostics:false,render_width:0,ui_notice:String::new(),issue:None,
            setup_epoch:String::new(),setup_state:"unknown".into(),setup_checked_at:0,
            setup_forwarding_paused:false,
            resume_requested:false,
            diagnostic_kind:String::new(),diagnostic_deadline:0,diagnostic_done_at:0,test_passed:false,
            last_render_signature:String::new(),
            config: Config::default(),
            saved_config:None,
            bridge: Bridge::default(),
            server_id: None,
            tick: None,
            devices: Vec::new(),
            known_devices: Vec::new(),
            subscribed: String::new(),
            registration_pending:false,registration_failed:false,
            ui_id: String::new(),
            error: String::new(),
            probe_last: Value::Null,
            delivery:LaunchDelivery::default(),probe_pending:false,reconnect_attempts:0,reconnect_at:0,launch_validated:false,launch_status:"尚未测试唤起".into(),watch_visible:false,watch_seen:0,
            watch_rx_count:0,watch_rx_kind:String::new(),watch_reply_error:String::new(),
            watch_rx_shape:Value::Null,
        }
    }
}
static APP: OnceLock<Mutex<App>> = OnceLock::new();
#[cfg(test)]
mod diagnostic_tests {
    use super::*;
    #[test]
    fn structure_diagnostic_excludes_secrets_and_unknown_keys() {
        let frame=json!({"v":1,"type":"hello","ticket":"SECRET_TICKET","arbitrary-secret-key":"SECRET_TEXT","data":{"content":"PRIVATE_BODY","token":"PRIVATE_TOKEN"}});
        let shape=frame_shape(&frame,0);
        let encoded=shape.to_string();
        for secret in ["SECRET_TICKET","SECRET_TEXT","PRIVATE_BODY","PRIVATE_TOKEN","arbitrary-secret-key"] {assert!(!encoded.contains(secret));}
        assert_eq!(shape["v1"],true);
        assert_eq!(shape["knownCommand"],true);
        assert_eq!(shape["fields"]["ticket"]["kind"],"string");
    }
    #[test]
    fn structure_diagnostic_bounds_nested_json() {
        let frame=json!({"data":{"payload":{"message":{"content":"PRIVATE"}}}});
        let shape=frame_shape(&frame,0);
        assert_eq!(shape["fields"]["data"]["fields"]["payload"],json!({"kind":"object"}));
        assert!(!shape.to_string().contains("PRIVATE"));
        let encoded=frame_shape(&json!(json!({"type":"hello"}).to_string()),0);
        assert_eq!(encoded["jsonShape"]["knownCommand"],true);
    }
}
fn app() -> &'static Mutex<App> {
    APP.get_or_init(|| Mutex::new(App::default()))
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
fn random_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| "安全随机数不可用".to_string())?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
fn save_config() -> Result<(), String> {
    let (config,epoch)={let state=app().lock().unwrap();(state.config.clone(),state.setup_epoch.clone())};
    let client =
        json!({"endpoint":format!("http://127.0.0.1:{}",config.port),"token":config.token,"deliveryMode":"launch","pluginVersion":VERSION,"setupApiVersion":1,"setupEpoch":epoch});
    atomic_write(
        "bridge-client.json",
        serde_json::to_vec_pretty(&client).unwrap(),
    )
    .map_err(|_| "导出 hook 连接配置失败".to_string())?;
    if atomic_write(CONFIG_FILE,serde_json::to_vec_pretty(&config).map_err(|e|e.to_string())?).is_err(){
        if std::path::Path::new("bridge-client.json.bak").exists(){let _=std::fs::rename("bridge-client.json.bak","bridge-client.json");}
        return Err("保存设置失败；保留上一份有效配置".into());
    }
    app().lock().unwrap().saved_config=Some(config);Ok(())
}
fn atomic_write(path: &str, bytes: Vec<u8>) -> std::io::Result<()> {
    use std::io::Write;
    let tmp=format!("{path}.tmp");
    let mut file=std::fs::File::create(&tmp)?;
    file.write_all(&bytes)?;file.sync_all()?;drop(file);
    if std::path::Path::new(path).exists(){std::fs::copy(path,format!("{path}.bak"))?;}
    std::fs::rename(tmp,path)
}
fn save_or_report() {
    if let Err(error)=save_config(){
        {let mut state=app().lock().unwrap();if let Some(old)=state.saved_config.clone(){state.config=old;state.bridge.device_addr=state.config.device_addr.clone();}
            state.config.enabled=false;state.config.scheme_b_enabled=false;state.bridge.enabled=false;state.bridge.suspend("unavailable");state.reconnect_at=0;state.probe_pending=false;}
        set_issue("bridge","CONFIG_SAVE_FAILED",&error,None);
    }
}
fn set_error(error: &str) {
    let mut state=app().lock().unwrap();state.error=error.into();state.ui_notice=error.into();
}
fn set_issue(stage:&str,code:&str,message:&str,native:Option<&str>) {
    let mut state=app().lock().unwrap();state.error=message.into();
    state.issue=Some(Issue{stage:stage.into(),code:code.into(),message:message.into(),
        native_code:native.and_then(bridge_core::dashboard::native_error)});
}
fn facts(state:&App)->Facts {
    Facts{bound:!state.config.device_addr.is_empty(),bluetooth:state.devices.iter().any(|(_,a)|a==&state.config.device_addr),watch_bound:state.bridge.watch_bound,watch_binding_reason:state.bridge.watch_binding_reason.clone(),
        bridge_enabled:state.config.enabled,http_ready:state.server_id.is_some(),registered:!state.subscribed.is_empty() && state.subscribed==state.config.device_addr,
        registering:state.registration_pending,setup_ready:matches!(state.setup_state.as_str(),"ready"|"cached"),setup_invalid:state.setup_state=="invalid",
        hook_verified:state.bridge.hook_ready(now()),hook_paused:state.setup_forwarding_paused,launch_validated:state.launch_validated,push_enabled:state.config.scheme_b_enabled,
        launch_waiting:state.delivery.waiting || state.probe_pending,test_passed:state.test_passed,issue:state.issue.clone()}
}
fn audio_validated(firmware: &str) -> bool {
    if firmware.is_empty() {
        return false;
    }
    let record: Value = std::fs::read("audio-validation.json")
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(Value::Null);
    let addr = app().lock().unwrap().config.device_addr.clone();
    record["deviceAddr"] == addr
        && record["firmware"] == firmware
        && record["validated"] == true
        && record["background60s"] == true
        && record["background300s"] == true
        && record["background1800s"] == true
        && record["audioInterruptionHandled"] == true
        && record["stopReleasesAudio"] == true
        && record["batteryCompared"] == true
}
async fn remove_notifications(_ids: Vec<u32>) {
    // Local queue cleanup only. Notification removal is also a device write.
}
async fn refresh_devices() {
    let connected = device::get_connected_device_list().await;
    let known = device::get_device_list().await;
    let mut candidates:Vec<(String,String)>=known.into_iter().map(|d|(d.name,d.addr)).collect();
    let addresses: Vec<(String, String)> =
        connected.into_iter().map(|d| (d.name, d.addr)).collect();
    for d in &addresses {if !candidates.iter().any(|(_,a)|a==&d.1){candidates.push(d.clone());}}
    let (removed, subscribe) = {
        let mut state = app().lock().unwrap();
        let online = addresses
            .iter()
            .any(|(_, addr)| *addr == state.config.device_addr);
        if online && state.issue.as_ref().is_some_and(|e|e.stage=="device"){state.issue=None;}
        state.devices = addresses;
        state.known_devices=candidates;
        let registered=online && state.subscribed==state.config.device_addr;
        let removed = state.bridge.set_online(registered);
        let subscribe = if state.bridge.enabled && online && !registered && !state.registration_pending && !state.registration_failed {
            state.registration_pending=true;
            Some(state.config.device_addr.clone())
        } else {
            None
        };
        if !online {
            if state.config.scheme_b_enabled || !state.delivery.nonce.is_empty() || !state.delivery.queued.is_empty(){state.config.scheme_b_enabled=false;state.delivery.fail();state.launch_status="蓝牙断开，已停止自动唤起".into();state.issue=Some(Issue{stage:"device".into(),code:"DEVICE_DISCONNECTED".into(),message:"手环蓝牙连接已断开".into(),native_code:None});}
            state.launch_validated=false;
            state.subscribed.clear();
            state.registration_failed=false;
        }
        (removed, subscribe)
    };
    remove_notifications(removed).await;
    if let Some(addr) = subscribe {
        let result=register::register_interconnect_recv(addr.clone(), PACKAGE.into()).await;
        let mut state=app().lock().unwrap();state.registration_pending=false;
        if state.config.device_addr==addr {
            match result {
                Ok(()) => {
                    state.subscribed=addr;
                    if state.issue.as_ref().is_some_and(|e|matches!(e.code.as_str(),"INTERCONNECT_PERMISSION"|"INTERCONNECT_REGISTER_FAILED")){state.issue=None;}
                    let present=state.devices.iter().any(|(_,known)|known==&state.config.device_addr);
                    state.bridge.set_online(present);
                    state.registration_failed=false;
                    if state.error.starts_with("Interconnect 接收注册失败"){state.error.clear();}
                },
                Err(error)=>{
                    state.registration_failed=true;
                    state.issue=Some(Issue{stage:"bridge".into(),code:if error.contains("permission"){"INTERCONNECT_PERMISSION".into()}else{"INTERCONNECT_REGISTER_FAILED".into()},message:"互联接收注册失败".into(),native_code:bridge_core::dashboard::native_error(&error)});
                    state.error=format!("Interconnect 接收注册失败：{}。请允许 register_interconnect_recv，然后点击刷新设备。",error.chars().take(160).collect::<String>());
                },
            }
        }
    }
}
async fn start_server() {
    if app().lock().unwrap().server_id.is_some() {
        return;
    }
    let port = app().lock().unwrap().config.port;
    match http_server::start(http_server::ServerOptions {
        port,
        bind_all_interfaces: false,
    })
    .await
    {
        Ok(info) => {
            let mut state = app().lock().unwrap();
            if !state.bridge.enabled {drop(state);let _=http_server::stop(info.id).await;return;}
            state.server_id = Some(info.id);
            if state.tick.is_none() {
                state.tick = Some(timer::set_interval(1000, "tick"));
            }
        }
        Err(error) => {
            let mut state = app().lock().unwrap();
            state.config.enabled = false;
            state.bridge.enabled = false;
            state.error = "本机 HTTP 端口启动失败；检查端口 37121 和插件权限".into();
            state.issue=Some(Issue{stage:"bridge".into(),code:"HTTP_START_FAILED".into(),message:state.error.clone(),native_code:bridge_core::dashboard::native_error(&error)});
        }
    }
}
async fn stop_bridge(stop_server: bool) {
    let (removed, server, tick, addr, ticket) = {
        let mut state = app().lock().unwrap();
        state.config.enabled = false;
        state.bridge.enabled = false;
        state.delivery=LaunchDelivery::default();state.reconnect_at=0;state.reconnect_attempts=0;state.probe_pending=false;state.launch_validated=false;state.config.scheme_b_enabled=false;
        state.resume_requested=false;
        state.diagnostic_kind.clear();state.diagnostic_done_at=0;state.diagnostic_deadline=0;
        let ticket=state.bridge.ticket.clone();
        let removed = state.bridge.suspend("unavailable");
        if state.bridge.watch_bound!=Some(false){state.bridge.watch_bound=None;state.bridge.watch_binding_reason="feature_off".into();}
        let server = if stop_server {
            state.server_id.take()
        } else {
            None
        };
        let tick = if stop_server { state.tick.take() } else { None };
        (removed, server, tick,state.config.device_addr.clone(),ticket)
    };
    save_or_report();
    if stop_server && !addr.is_empty() && !ticket.is_empty(){
        let _=interconnect::send_qaic_message(addr,PACKAGE.into(),json!({"v":1,"type":"unavailable","ticket":ticket}).to_string()).await;
    }
    remove_notifications(removed).await;
    if let Some(id) = tick {
        timer::clear_timer(id);
    }
    if let Some(id) = server {
        let _ = http_server::stop(id).await;
    }
}
async fn finish_diagnostic() {
    let outcome={let s=app().lock().unwrap();if s.diagnostic_kind.is_empty(){None}else{
        let complete=s.diagnostic_done_at!=0 && now()>=s.diagnostic_done_at;
        let probe=s.diagnostic_kind=="connection";
        if complete || (probe && (s.launch_validated || s.delivery.faulted)) || now()>=s.diagnostic_deadline {Some((probe,s.launch_validated))}else{None}
    }};
    if let Some((probe,passed))=outcome {stop_bridge(true).await;let mut s=app().lock().unwrap();if probe{s.test_passed=passed;s.ui_notice=if passed{"连接测试通过；临时服务已停止，总开关保持关闭"}else{"连接测试未通过；临时服务已停止，请确认手环应用已打开"}.into();}}
}
async fn reconcile_feature() {
    let (changed,resume)={
        let mut s=app().lock().unwrap();
        let ready=bridge_core::dashboard::delivery_can_start(&facts(&s),s.delivery.faulted) && s.bridge.online;
        let changed=ready && !s.config.scheme_b_enabled;
        if ready{s.config.scheme_b_enabled=true;}
        (changed,false)
    };
    if changed{save_or_report();}
    let _=resume;
}
fn response(status: u16, body: Value) -> http_server::Response {
    http_server::Response {
        status,
        headers: vec![
            http_server::Header {
                name: "content-type".into(),
                value: "application/json; charset=utf-8".into(),
            },
            http_server::Header {
                name: "cache-control".into(),
                value: "no-store".into(),
            },
        ],
        body: serde_json::to_vec(&body).unwrap(),
    }
}
fn error_response(status: u16, error: &str) -> http_server::Response {
    response(status, json!({"error":error}))
}
fn authorized(headers: &[http_server::Header]) -> bool {
    let state = app().lock().unwrap();
    if state.config.token.len() < 32 {
        return false;
    }
    // Constant-work byte comparison: don't expose a prefix oracle for the access token.
    let expected = format!("Bearer {}", state.config.token);
    let value = headers
        .iter()
        .find(|h| h.name.eq_ignore_ascii_case("authorization"))
        .map(|h| h.value.as_str())
        .unwrap_or("");
    let mut diff = expected.len() ^ value.len();
    for (index, byte) in expected.bytes().enumerate() {
        diff |= (byte ^ value.as_bytes().get(index).copied().unwrap_or(0)) as usize;
    }
    diff == 0
}
fn pending_ids(state: &App) -> BTreeSet<String> {
    state.bridge.requests.iter().filter(|(_,r)|r.state=="pending" && (r.expires_at_ms==0 || now()<r.expires_at_ms)).map(|(id,_)|id.clone()).collect()
}
fn decorate(state: &mut App, result: &mut Value) {
    let pending=pending_ids(state);state.delivery.prune(&pending);
    result["deliveryMode"]=json!("launch");result["safetyPaused"]=json!(!state.config.scheme_b_enabled);
    if result.get("requests").is_some() {
        if let Some(rows)=result["requests"].as_array_mut(){rows.retain(|r|r["id"].as_str().is_some_and(|id|state.delivery.delivered.contains(id)));}
    }
    if state.delivery.waiting && !state.delivery.nonce.is_empty() && result["type"]=="hello" {
        result["launchNonce"]=json!(state.delivery.nonce);
    }
}
async fn push_request(id: &str) -> Result<(), String> {
    let mut state=app().lock().unwrap();
    if !state.config.scheme_b_enabled {return Err("delivery_paused".into());}
    if state.delivery.faulted {return Err("launch_faulted".into());}
    state.delivery.queue(id);Ok(())
}
async fn process_wake() {
    let nonce=match random_token(){Ok(nonce)=>nonce,Err(_)=>return};
    let work={
        let mut state=app().lock().unwrap();let pending=pending_ids(&state);state.delivery.prune(&pending);
        if state.delivery.expired(now()) {state.delivery.fail();state.launch_status="应用就绪超时，已停止自动唤起；电脑仍可授权".into();state.issue=Some(Issue{stage:"push".into(),code:"PUSH_READY_TIMEOUT".into(),message:state.launch_status.clone(),native_code:None});}
        if !state.bridge.online || !state.bridge.enabled {None}
        else {
            let probe=state.probe_pending;
            if (probe || state.config.scheme_b_enabled) && state.delivery.begin(nonce.clone(),now(),probe) {
                state.probe_pending=false;state.launch_status="正在请求打开手环应用".into();Some(state.config.device_addr.clone())
            }else{None}
        }
    };
    let Some(addr)=work else{return};
    let mut launch_native=None;
    let outcome=async {
        let apps=thirdpartyapp::get_thirdparty_app_list(addr.clone()).await.map_err(|error|{launch_native=bridge_core::dashboard::native_error(&error);"应用列表读取失败；检查 thirdpartyapp 权限"})?;
        let info=apps.into_iter().find(|a|a.package_name==PACKAGE && a.version_code>=11008).ok_or("请先安装已验证的手环应用（1.1.8 或更新）")?;
        let allowed={let mut state=app().lock().unwrap();let pending=pending_ids(&state);state.delivery.prune(&pending);state.config.device_addr==addr && state.bridge.enabled && state.bridge.online && state.delivery.nonce==nonce};
        if !allowed{return Err("唤起请求已取消")}
        thirdpartyapp::launch_qa(addr.clone(),info,"pages/index".into()).await.map_err(|error|{launch_native=bridge_core::dashboard::native_error(&error);"应用唤起请求失败"})?;
        Ok(())
    }.await;
    let challenge={
        let mut state=app().lock().unwrap();let pending=pending_ids(&state);state.delivery.prune(&pending);
        if state.delivery.nonce!=nonce || state.config.device_addr!=addr {None}
        else if let Err(error)=outcome {state.delivery.fail();state.launch_status=error.into();state.issue=Some(Issue{stage:"push".into(),code:match error {"应用列表读取失败；检查 thirdpartyapp 权限"=>"WATCH_APP_LIST_FAILED","请先安装已验证的手环应用（1.1.8 或更新）"=>"WATCH_UPGRADE_REQUIRED",_=>"PUSH_LAUNCH_FAILED"}.into(),message:state.launch_status.clone(),native_code:launch_native.clone()});None}
        else {state.delivery.launched();state.launch_status="等待本次应用就绪确认".into();
            if state.bridge.ticket.is_empty(){None}else{Some(json!({"v":1,"type":"launch_probe","ticket":state.bridge.ticket,"nonce":nonce}))}
        }
    };
    if let Some(frame)=challenge {
        if interconnect::send_qaic_message(addr,PACKAGE.into(),frame.to_string()).await.is_err() {
            let mut state=app().lock().unwrap();state.delivery.fail();state.launch_status="就绪探针发送失败，已停止重试".into();state.issue=Some(Issue{stage:"push".into(),code:"PUSH_PROBE_FAILED".into(),message:state.launch_status.clone(),native_code:None});
        }
    }
    render();
}
fn render() {
    let (id,model,selected,devices,width,notice,enabled,addr,diagnostics,epoch,rejected)={
        let mut state=app().lock().unwrap();let f=facts(&state);let model=stages(&f);
        let selected=bridge_core::dashboard::selection(state.manual_selection,state.selected_stage.as_deref(),&model,state.config.enabled);
        if selected!=state.selected_stage {state.ui_notice.clear();state.diagnostics=false;}state.selected_stage=selected;
        let signature=json!([model,state.selected_stage,state.devices,state.known_devices,state.render_width,state.ui_notice,state.config.enabled,state.config.device_addr,state.diagnostics,state.power_rejected]).to_string();
        if signature==state.last_render_signature{return;}state.last_render_signature=signature;
        (state.ui_id.clone(),model,state.selected_stage.clone(),state.known_devices.iter().map(|(n,a)|(format!("{n}（{}）",if state.devices.iter().any(|(_,online)|online==a){"蓝牙在线"}else{"离线"}),a.clone())).collect::<Vec<_>>(),state.render_width,state.ui_notice.clone(),state.config.enabled,state.config.device_addr.clone(),state.diagnostics,state.setup_epoch.clone(),state.power_rejected)
    };
    if !id.is_empty(){dashboard_ui::render(&id,&model,selected.as_deref(),&devices,width,&notice,enabled,&addr,diagnostics,&epoch,rejected);}
}

struct Plugin;
impl lifecycle::Guest for Plugin {
    async fn on_load() {
        if std::path::Path::new(CONFIG_FILE).exists() && !std::path::Path::new("settings.pre-2.0.0.json").exists() {
            if std::fs::copy(CONFIG_FILE,"settings.pre-2.0.0.json").is_err(){set_issue("bridge","CONFIG_BACKUP_FAILED","旧配置备份失败，未修改配置",None);return;}
        }
        let mut config: Config = match std::fs::read(CONFIG_FILE) {
            Ok(bytes)=>match serde_json::from_slice(&bytes){Ok(config)=>config,Err(_)=>{set_issue("bridge","CONFIG_INVALID","设置文件无法解析，保留原文件和备份，未重置绑定",None);return;}},
            Err(error) if error.kind()==std::io::ErrorKind::NotFound=>Config::default(),
            Err(_)=>{set_issue("bridge","CONFIG_READ_FAILED","设置文件无法读取，未修改绑定",None);return;}
        };
        config.scheme_b_enabled=false;
        if config.token.is_empty() {
            match random_token() {
                Ok(token) => config.token = token,
                Err(error) => {
                    set_error(&error);
                    return;
                }
            }
        }
        // Installation-scoped identity survives plugin/token replacement.
        // Never advertise a rotating access token as the pinned computer identity.
        config.host_id=match os::device_id().await {
            Ok(id) if !id.trim().is_empty()=>id,
            _=>{set_issue("bridge","HOST_ID_UNAVAILABLE","电脑身份读取失败：请允许 os.device-id 权限并重新加载插件；桥接未启动",None);return;}
        };
        {
            let mut state = app().lock().unwrap();
            if config.hooks_install_command_version.is_empty() {config.enabled=false;config.scheme_b_enabled=false;}
            state.bridge.enabled = config.enabled;
            state.bridge.device_addr = config.device_addr.clone();
            state.bridge.host_id = config.host_id.clone();
            state.config = config;
            state.setup_epoch=random_token().unwrap_or_default();
        }
        if let Err(error) = save_config() {
            set_error(&error);
            return;
        }
        if app().lock().unwrap().bridge.enabled {start_server().await;app().lock().unwrap().probe_pending=true;}
        refresh_devices().await;
    }
}
impl http::Guest for Plugin {
    async fn handle(_server_id: u32, request: http_server::Request) -> http_server::Response {
        if !authorized(&request.headers) {
            return error_response(401, "unauthorized");
        }
        if request
            .headers
            .iter()
            .any(|h| h.name.eq_ignore_ascii_case("origin"))
        {
            return error_response(403, "origin_not_allowed");
        }
        let removed = app().lock().unwrap().bridge.expire(now());
        remove_notifications(removed).await;
        if request.method=="POST" && request.path=="/v1/hook-health" {
            let Ok(value)=serde_json::from_slice::<Value>(&request.body) else {return error_response(400,"invalid_json");};
            let mut state=app().lock().unwrap();
            if !state.bridge.record_hook(value["event"].as_str().unwrap_or(""),now()) {return error_response(400,"invalid_event");}

            let result=json!({"ok":true,"hookReady":state.bridge.hook_ready(now())});drop(state);render();
            return response(200,result);
        }
        if request.method=="POST" && request.path=="/v1/setup-report" {
            if request.body.len()>4096{return error_response(413,"too_large");}
            let Ok(_value)=serde_json::from_slice::<Value>(&request.body) else{return error_response(400,"invalid_json");};
            // Backward-compatible acknowledgement; configuration inspection is no longer used.
            return response(200,json!({"ok":true,"ignored":true}));
        }

        if request.method == "GET" && request.path == "/v1/status" {
            let state = app().lock().unwrap();
            return response(
                200,
                json!({"v":1,"pluginVersion":VERSION,"setupApiVersion":1,"setupEpoch":state.setup_epoch,"stages":stages(&facts(&state)),"diagnosticTime":now(),"hookReady":state.bridge.hook_ready(now()),"hookExecutionSeen":state.bridge.hook_last_seen_ms!=0,"hookLastSeenMs":state.bridge.hook_last_seen_ms,"hookConfigState":state.setup_state,"hookConfigCheckedAt":state.setup_checked_at,"hookForwardingPaused":state.setup_forwarding_paused,"hookConfigCached":state.setup_state=="cached","hookConfigurationDetection":false,"hookRoutingActive":state.config.scheme_b_enabled && !state.delivery.faulted && state.bridge.enabled && state.bridge.online,"deliveryMode":"launch","safetyPaused":!state.config.scheme_b_enabled,"launchValidated":state.launch_validated,"launchStatus":state.launch_status,"launchFaulted":state.delivery.faulted,"enabled":state.config.enabled,"diagnosticMode":state.diagnostic_kind,"online":state.bridge.online,
                "hostId":state.bridge.host_id,"deviceAddr":state.bridge.device_addr,"pending":state.bridge.summaries().len(),
                "bluetoothOnline":state.devices.iter().any(|(_,addr)|addr==&state.config.device_addr),
                "interconnectRegistered":!state.subscribed.is_empty() && state.subscribed==state.config.device_addr,
                "watchHandshake":!state.bridge.ticket.is_empty(),"watchBound":state.bridge.watch_bound,"watchBindingReason":state.bridge.watch_binding_reason,"registrationPending":state.registration_pending,
                "selectedDeviceAddr":state.config.device_addr,"devices":state.known_devices.iter().map(|(name,addr)|json!({"name":name,"addr":addr,"connected":state.devices.iter().any(|(_,a)|a==addr),"selected":addr==&state.config.device_addr})).collect::<Vec<_>>(),
                "watchRxCount":state.watch_rx_count,"watchRxKind":state.watch_rx_kind,"watchReplyError":state.watch_reply_error,"watchRxShape":state.watch_rx_shape}),
            );
        }
        if request.method == "GET" && request.path == "/v1/probe" {
            let state = app().lock().unwrap();
            return response(
                200,
                if state.probe_last.is_null() {
                    json!({})
                } else {
                    state.probe_last.clone()
                },
            );
        }
        if request.method == "POST" && request.path == "/v1/requests" {
            if !app().lock().unwrap().config.scheme_b_enabled {return error_response(503,"delivery_paused");}
            if request.body.len() > 128 * 1024 {
                return error_response(413, "too_large");
            }
            let Ok(input) = serde_json::from_slice::<NewRequest>(&request.body) else {
                return error_response(400, "invalid_json");
            };
            let id = input.id.clone();
            app().lock().unwrap().bridge.record_hook(if input.kind=="approval"{"PermissionRequest"}else{"PreToolUse"},now());
            let created = app().lock().unwrap().bridge.create(input, now());
            match created {
                Ok((_, true)) => {
                    if push_request(&id).await.is_err() {
                        let removed = app().lock().unwrap().bridge.cancel(&id);
                        remove_notifications(removed.into_iter().collect()).await;
                        return error_response(503, "launch_delivery_unavailable");
                    }
                    return response(201, json!({"id":id,"state":"pending"}));
                }
                Ok((_, false)) => return response(200, json!({"id":id,"state":"pending"})),
                Err(error) => {
                    return error_response(if error == "unavailable" { 503 } else { 400 }, error);
                }
            }
        }
        if let Some(id) = request.path.strip_prefix("/v1/requests/") {
            if request.method == "POST" && id.ends_with("/decision") {
                let key=id.trim_end_matches("/decision");
                let Ok(value)=serde_json::from_slice::<Value>(&request.body) else {return error_response(400,"invalid_json");};
                let (result, notification_id, addr, ticket) = {
                    let mut state=app().lock().unwrap();
                    let result=state.bridge.desktop_decision(key,value["session_id"].as_str().unwrap_or(""),value["decision"].as_str().unwrap_or(""),now());
                    let nid=state.bridge.requests.get(key).map(|r|r.notification_id);
                    (result,nid,state.config.device_addr.clone(),state.bridge.ticket.clone())
                };
                return match result {
                    Ok(value)=>{
                        remove_notifications(notification_id.into_iter().collect()).await;
                        if !ticket.is_empty() {
                            let frame=json!({"v":1,"type":"result","id":key,"state":value["state"],"source":value["resolvedBy"],"ticket":ticket});
                            let _=interconnect::send_qaic_message(addr,PACKAGE.into(),frame.to_string()).await;
                        }
                        response(200,value)
                    },
                    Err(error)=>error_response(409,error),
                };
            }
            if request.method == "GET" {
                let mut state = app().lock().unwrap();
                state.bridge.renew_hook(id,now());
                let Some(item) = state.bridge.requests.get(id) else {
                    return error_response(404, "not_found");
                };
                return response(
                    200,
                    json!({"id":item.input.id,"session_id":item.input.session_id,"state":item.state,"expires_at_ms":item.expires_at_ms,
                        "watchAvailable":state.bridge.online && !state.delivery.faulted && state.delivery.delivered.contains(id)}),
                );
            }
            if request.method == "DELETE" {
                let removed = app().lock().unwrap().bridge.cancel(id);
                remove_notifications(removed.into_iter().collect()).await;
                return response(200, json!({"id":id,"cancelled":true}));
            }
        }
        if request.method == "DELETE" {
            if let Some(session) = request.path.strip_prefix("/v1/sessions/") {
                // Hook session IDs are UUID/ASCII identifiers. No session path is used for filesystem access.
                let removed = {
                    let mut state = app().lock().unwrap();
                    let ids = state
                        .bridge
                        .requests
                        .iter()
                        .filter(|(_, r)| r.input.session_id == session && r.state == "pending")
                        .map(|(id, _)| id.clone())
                        .collect::<Vec<_>>();
                    ids.iter()
                        .filter_map(|id| state.bridge.cancel(id))
                        .collect::<Vec<_>>()
                };
                remove_notifications(removed).await;
                return response(200, json!({"cancelled":true}));
            }
        }
        error_response(404, "not_found")
    }
}
impl event::Guest for Plugin {
    async fn on_event(kind: event::EventType, payload: String) -> String {
        match kind {
            event::EventType::Timer | event::EventType::DeviceAction => {
                if !app().lock().unwrap().bridge.enabled {return String::new();}
                if app().lock().unwrap().diagnostic_kind=="hooks" {finish_diagnostic().await;render();return String::new();}
                refresh_devices().await;
                let removed = app().lock().unwrap().bridge.expire(now());
                remove_notifications(removed).await;
                process_wake().await;
                reconcile_feature().await;
                finish_diagnostic().await;
                let size=ui::get_render_size().await;
                app().lock().unwrap().render_width=size.width;
            }
            event::EventType::InterconnectMessage => {
                if !app().lock().unwrap().bridge.enabled {return String::new();}
                if app().lock().unwrap().diagnostic_kind=="hooks" {return String::new();}
                if payload.len() > 16 * 1024 {
                    return String::new();
                }
                let addr=app().lock().unwrap().config.device_addr.clone();
                let decoded=decode_interconnect_event(&payload,&addr,PACKAGE);
                {
                    let mut state=app().lock().unwrap();state.watch_rx_count+=1;
                    state.watch_rx_shape=serde_json::from_str::<Value>(&payload).map(|value|frame_shape(&value,0)).unwrap_or(json!({"kind":"invalid_json"}));
                    state.watch_rx_kind=match &decoded {
                        Ok((frame,encoded))=>{let kind=match frame["type"].as_str(){Some("hello")=>"hello",Some("ready")=>"ready",Some("list")=>"list",Some("ping")=>"ping",Some("detail")=>"detail",Some("decision")=>"decision",Some("binding")=>"binding",_=>"other"};format!("{}{}",kind,if *encoded {" (double JSON)"}else{""})},
                        Err(error)=>(*error).into(),
                    };
                }
                let Ok((message,_))=decoded else{render();return String::new();};
                // Unknown frames must not trigger unsolicited replies on the device.
                if message["v"].as_u64()!=Some(1) || !matches!(message["type"].as_str(),Some("hello"|"list"|"ping"|"detail"|"page_read"|"decision"|"stop"|"resume"|"ready"|"binding")) {
                    render();return String::new();
                }
                if matches!(message["type"].as_str(),Some("detail"|"page_read"|"decision")) && !app().lock().unwrap().delivery.delivered.contains(message["id"].as_str().unwrap_or("")) {return String::new();}
                let Ok(ticket) = random_token() else {
                    return String::new();
                };
                let (addr, mut result, notification_ids) = {
                    let mut state = app().lock().unwrap();
                    let pending: Vec<String> = state
                        .bridge
                        .requests
                        .iter()
                        .filter(|(_, r)| r.state == "pending")
                        .map(|(id, _)| id.clone())
                        .collect();
                    let mut command=message.clone();
                    let mut alert_ids=Vec::new();
                    if message["type"]=="ready" {
                        let pending=pending_ids(&state);state.delivery.prune(&pending);
                        let authenticated=!state.bridge.ticket.is_empty() && message["ticket"].as_str()==Some(state.bridge.ticket.as_str());
                        let probe=state.delivery.probe;
                        if let Some(ids)=state.delivery.ready(message["nonce"].as_str().unwrap_or(""),now(),authenticated,message["visible"].as_bool()==Some(true)) {
                            state.launch_status="已确认手环应用就绪".into();if state.issue.as_ref().is_some_and(|e|e.stage=="push"){state.issue=None;}if probe {state.launch_validated=true;}
                            alert_ids=ids;state.delivery.probe=false;
                        }
                        command["type"]=json!("list");
                    }
                    let mut result = state.bridge.watch_message(&command, now(), &ticket);
                    decorate(&mut state,&mut result);
                    if !alert_ids.is_empty() {result["alertIds"]=json!(alert_ids.iter().take(4).collect::<Vec<_>>());result["wakeRequestId"]=json!(alert_ids[0]);}
                    if result["type"]=="hello" || message["ticket"].as_str()==Some(state.bridge.ticket.as_str()) {
                        state.watch_visible=message["visible"].as_bool().unwrap_or(true);state.watch_seen=now();
                    }
                    if result["type"] == "pong" && message["probeStats"].is_object() {
                        state.probe_last = json!({"deviceAddr":state.bridge.device_addr,"receivedAt":now(),"probe":message["probeStats"]});
                    }
                    if !state.bridge.ticket.is_empty()
                        && message["ticket"].as_str() == Some(state.bridge.ticket.as_str())
                        && result.get("ticket").is_none()
                    {
                        result["ticket"] = json!(state.bridge.ticket);
                    }
                    let notification_ids = pending
                        .iter()
                        .filter_map(|id| state.bridge.requests.get(id))
                        .filter(|r| r.state != "pending")
                        .map(|r| r.notification_id)
                        .collect::<Vec<_>>();
                    if state.diagnostic_kind.is_empty(){state.config.enabled = state.bridge.enabled;}
                    if result["type"]=="binding" && result["bound"]==false {
                        state.config.scheme_b_enabled=false;
                        state.launch_validated=false;
                        state.delivery=LaunchDelivery::default();
                        state.launch_status="手环已解除电脑绑定，推送已暂停".into();
                    }
                    (state.config.device_addr.clone(), result, notification_ids)
                };
                if result["type"] == "hello" {
                    result["experimentalAudioValidated"] =
                        json!(audio_validated(message["firmware"].as_str().unwrap_or("")));
                }
                if result["type"] == "stopped" || (result["type"]=="binding" && result["bound"]==false) {
                    stop_bridge(true).await;
                } else if result["type"] == "resumed" {
                    save_or_report();
                }
                let sent=interconnect::send_qaic_message(addr, PACKAGE.into(), result.to_string()).await;
                {
                    let mut state=app().lock().unwrap();
                    state.watch_reply_error=match sent {Ok(())=>{if state.issue.as_ref().is_some_and(|e|e.code=="INTERCONNECT_REPLY_FAILED"){state.issue=None;}String::new()},Err(error)=>{
                        state.issue=Some(Issue{stage:"bridge".into(),code:"INTERCONNECT_REPLY_FAILED".into(),message:"互联回复发送失败".into(),native_code:bridge_core::dashboard::native_error(&error)});
                        if error.contains("permission denied"){"回复未获授权".into()}else if error.contains("not found"){"手环应用未在列表中找到".into()}else{"互联回复发送失败".into()}
                    }};
                    if !state.watch_reply_error.is_empty(){state.error=state.watch_reply_error.clone();}
                }
                remove_notifications(notification_ids).await;
            }
            _ => {}
        }
        render();
        String::new()
    }
    async fn on_ui_event(id: String, _event: ui::Event, _payload: String) -> String {
        if id=="toggle_diagnostics"{let mut state=app().lock().unwrap();state.diagnostics=!state.diagnostics;drop(state);render();return String::new();}
        if let Some(stage)=id.strip_prefix("stage:") {
            if bridge_core::dashboard::IDS.contains(&stage){let mut state=app().lock().unwrap();state.manual_selection=true;state.selected_stage=Some(stage.into());state.ui_notice.clear();state.diagnostics=false;}
            render();return String::new();
        }
        if id=="overview" {let mut state=app().lock().unwrap();state.manual_selection=false;state.ui_notice.clear();drop(state);render();return String::new();}
        if id=="copy_install" {
            {let mut state=app().lock().unwrap();state.config.hooks_install_command_version=VERSION.into();}
            save_or_report();
            let epoch=app().lock().unwrap().setup_epoch.clone();
            let command=hook_commands::script("Configure-Codex.ps1",false,&epoch);
            let copied=clipboard::write_text(command).await.is_ok();
            app().lock().unwrap().ui_notice=if copied {"安装命令已复制，请在 PowerShell 中运行。"}else{"复制未成功，请选中命令按 Ctrl+C；在 AstroBox 允许插件写入剪贴板。"}.into();
            render();return String::new();
        }
        if let Some(addr) = id.strip_prefix("bind:") {
            if app().lock().unwrap().config.device_addr==addr {render();return String::new();}
            let removed = {
                let mut state = app().lock().unwrap();
                let removed = state.bridge.suspend("unavailable");
                if state.known_devices.iter().any(|(_, known)| known == addr) {
                    state.config.scheme_b_enabled=false;state.launch_validated=false;state.delivery=LaunchDelivery::default();
                    state.probe_pending=state.config.enabled;state.resume_requested=false;state.test_passed=false;
                    state.config.device_addr = addr.into();
                    state.bridge.device_addr = addr.into();
                    state.bridge.watch_bound=None;state.bridge.watch_binding_reason="device_changed".into();
                    state.subscribed.clear();
                    state.registration_failed=false;
                    state.issue=None;
                    state.probe_last = Value::Null;
                }
                removed
            };
            remove_notifications(removed).await;
            save_or_report();
            refresh_devices().await;
        } else {
            match id.as_str() {
                "launch_probe" => {
                    let mut state=app().lock().unwrap();
                    if state.config.device_addr.is_empty() || !state.devices.iter().any(|(_,a)|a==&state.config.device_addr){state.ui_notice="请先选择设备，并在 AstroBox 建立蓝牙连接".into();drop(state);render();return String::new();}
                    if !pending_ids(&state).is_empty(){state.ui_notice="请先处理完待授权请求，再测试连接".into();drop(state);render();return String::new();}
                    if !state.config.enabled {state.diagnostic_kind="connection".into();state.diagnostic_deadline=now()+25_000;state.diagnostic_done_at=0;state.bridge.enabled=true;}
                    state.test_passed=false;state.config.scheme_b_enabled=false;state.delivery=LaunchDelivery::default();state.registration_failed=false;
                    if state.issue.as_ref().is_some_and(|e|matches!(e.stage.as_str(),"device"|"bridge"|"push")){state.issue=None;}
                    state.probe_pending=true;state.launch_validated=false;state.launch_status="正在进行单次连接测试".into();drop(state);start_server().await;refresh_devices().await;
                },
                "toggle_service" => {
                    let enabled=app().lock().unwrap().config.enabled;
                    if !enabled && app().lock().unwrap().config.hooks_install_command_version.is_empty() {
                        {let mut state=app().lock().unwrap();state.power_rejected=true;state.ui_notice="请先配置并信任钩子".into();state.manual_selection=true;state.selected_stage=Some("hooks".into());}
                        render();
                        dialog::show_dialog(dialog::DialogType::Alert,dialog::DialogStyle::Website,dialog::DialogInfo {
                            title:"无法启动".into(),content:"请先配置并信任钩子".into(),
                            buttons:vec![dialog::DialogButton{id:"ok".into(),primary:true,content:"知道了".into()}],
                        }).await;
                        app().lock().unwrap().power_rejected=false;render();return String::new();
                    }
                    if enabled {stop_bridge(true).await;}else{
                        let mut state=app().lock().unwrap();
                        if state.bridge.host_id.is_empty(){state.ui_notice="电脑身份未就绪，请允许 os.device-id 并重新加载插件".into();drop(state);render();return String::new();}
                        state.config.enabled=true;state.bridge.enabled=true;state.registration_failed=false;state.diagnostic_kind.clear();state.diagnostic_deadline=0;state.diagnostic_done_at=0;state.test_passed=false;
                        state.config.scheme_b_enabled=false;state.resume_requested=false;state.probe_pending=true;
                        if state.issue.as_ref().is_some_and(|e|matches!(e.code.as_str(),"HTTP_START_FAILED"|"INTERCONNECT_PERMISSION"|"INTERCONNECT_REGISTER_FAILED")){state.issue=None;}
                        drop(state);save_or_report();start_server().await;refresh_devices().await;
                    }
                },
                "refresh" => {app().lock().unwrap().registration_failed=false;refresh_devices().await;},
                "probe" => set_error("隔离版已禁用通知测试"),
                _ => {}
            }
        }
        render();
        String::new()
    }
    async fn on_ui_render(id: String) {
        let size=ui::get_render_size().await;
        let mut state=app().lock().unwrap();state.ui_id=id;state.render_width=size.width;state.last_render_signature.clear();drop(state);
        render();
    }
    async fn on_card_render(id: String) {
        ui::render_to_text_card(&id, "Codex 手环授权：打开插件设置查看状态");
    }
}
export!(Plugin);
