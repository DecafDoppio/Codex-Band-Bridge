//! Shared evidence-based setup status. Rendering never changes service state.
use serde::{Deserialize, Serialize};

pub const IDS: [&str; 3] = ["device", "connection", "hooks"];
pub fn native_error(value:&str)->Option<String> {
    let value=value.trim();
    if value.len()<16 && value.parse::<i64>().is_ok(){return Some(value.into());}
    let lower=value.to_ascii_lowercase();
    for category in ["permission denied","permission_denied","not found","unsupported","invalid_ticket"] {
        if lower==category || lower.starts_with(&format!("{category}:")){return Some(category.into());}
    }None
}
pub fn validate_setup_report(value:&serde_json::Value,epoch:&str)->Result<String,&'static str> {
    if epoch.is_empty() || value["epoch"].as_str()!=Some(epoch){return Err("stale_setup_report");}
    value["state"].as_str().filter(|s|matches!(*s,"ready"|"missing"|"invalid"))
        .map(str::to_string).ok_or("invalid_setup_state")
}
#[derive(Clone, Default, Serialize, Deserialize)]
pub struct Issue {
    pub stage: String,
    pub code: String,
    pub message: String,
    pub native_code: Option<String>,
}
#[derive(Default)]
pub struct Facts {
    /// A computer-side selected AstroBox device.
    pub bound: bool,
    pub bluetooth: bool,
    /// Only a post-hello, ticket-authenticated message from the watch can set
    /// this. `None` is intentionally distinct from a user unbind.
    pub watch_bound: Option<bool>,
    pub watch_binding_reason: String,
    pub bridge_enabled: bool,
    pub http_ready: bool,
    pub registered: bool,
    pub registering: bool,
    pub setup_ready: bool,
    pub setup_invalid: bool,
    pub hook_verified: bool,
    pub hook_paused: bool,
    pub launch_validated: bool,
    pub push_enabled: bool,
    pub launch_waiting: bool,
    pub test_passed: bool,
    pub issue: Option<Issue>,
}
#[derive(Clone, Serialize)]
pub struct Stage {
    pub id: String,
    pub title: String,
    pub status: String,
    pub message: String,
    pub code: Option<String>,
    pub native_code: Option<String>,
    pub solution: Vec<String>,
    pub steps: Vec<String>,
    pub actions: Vec<String>,
    pub status_label: Option<String>,
}
impl Stage {
    fn new(id:&str,title:&str,message:&str,steps:&[&str],actions:&[&str])->Self {
        Self{id:id.into(),title:title.into(),status:"yellow".into(),message:message.into(),
            code:None,native_code:None,solution:vec![],steps:steps.iter().map(|s|s.to_string()).collect(),
            actions:actions.iter().map(|s|s.to_string()).collect(),status_label:None}
    }
    fn healthy(&mut self){self.status="green".into();self.message="状态正常".into();self.steps.clear();}
    fn blocked(&mut self,by:&str){self.status="yellow".into();self.message=format!("请先完成{by}");self.steps.clear();self.code=None;self.native_code=None;self.solution.clear();}
}
pub fn solutions(code:&str)->Vec<String> {
    let items:&[&str]=match code {
        "DEVICE_DISCONNECTED"=>&["在 AstroBox 设备页重新连接手环。", "连接后点击刷新设备。"],
        "WATCH_UNBOUND"=>&["在手环应用设置页底部选择绑定当前电脑，并完成二次确认。", "保持应用前台和监听开启，等待电脑收到绑定确认。"],
        "INTERCONNECT_PERMISSION"=>&["在 AstroBox 中允许本插件的设备互联权限。", "打开手环应用并开启监听，再点击测试连接。"],
        "INTERCONNECT_REGISTER_FAILED"|"INTERCONNECT_REPLY_FAILED"=>&["确认手环已连到 AstroBox，应用已打开且监听开启。", "检查插件权限后点击测试连接。"],
        "HTTP_START_FAILED"=>&["在 AstroBox 中允许本插件的本机网络权限。", "关闭后重新打开总开关；仍失败时提供诊断信息。"],
        "HOST_ID_UNAVAILABLE"=>&["在 AstroBox 中允许插件读取电脑身份，然后重新打开插件。"],
        "CONFIG_INVALID"|"CONFIG_READ_FAILED"|"CONFIG_BACKUP_FAILED"|"CONFIG_SAVE_FAILED"=>&["设置暂时无法读写，请保留原文件并重新打开插件。", "仍失败时提供诊断信息，不要清除绑定。"],
        "WATCH_UPGRADE_REQUIRED"=>&["请安装本次交付的 1.3.0 手环应用，或已验证的 1.1.8 应用。", "打开手环应用，再点击仅测试连接。"],
        "HOOK_CONFIG_INVALID"=>&["运行下方安装命令修复 Hooks。", "在 ChatGPT 客户端进入设置 → 钩子，信任全部，并目视确认没有禁用或报错。"],
        "PUSH_READY_TIMEOUT"|"PUSH_PROBE_FAILED"=>&["打开手环应用，确认监听开启。", "点击测试连接，成功后自动恢复。"],
        "WATCH_APP_MISSING"=>&["在手环安装本应用。", "打开应用、开启监听，再测试连接。"],
        "WATCH_APP_LIST_FAILED"|"PUSH_LAUNCH_FAILED"=>&["确认手环应用已安装，在 AstroBox 允许插件打开设备应用。", "打开手环应用后重新测试连接。"],
        _=>&["确认设备连接和应用权限后重试。", "仍失败时提供展开后的诊断信息。"],
    };items.iter().map(|s|s.to_string()).collect()
}
pub fn stages(f:&Facts)->Vec<Stage> {
    let mut out=vec![
        Stage::new("device","选择设备","请选择要连接的手环",&["在 AstroBox 配对设备后，从列表勾选目标手环。"],&["refresh","devices"]),
        Stage::new("connection","双向连接","确认电脑和手环能互相回应",&["打开手环应用并开启监听。","点击测试连接；关闭总开关也能测试，结束后自动停止。"],&["launch_probe"]),
        Stage::new("hooks","Codex 钩子配置","按以下步骤接入 Codex 授权",&["复制下方命令，在 PowerShell 中运行。","ChatGPT 客户端 → 设置 → 钩子 → 信任全部。","确认本项目五项钩子已信任、未禁用，然后打开上方“启动 Codex Connector”开关。"],&[]),
    ];
    if f.bound {out[0].healthy();out[0].status_label=Some("已配置".into());out[0].message="已配置目标设备".into();}
    if !f.bound {out[1].blocked("选择设备");}
    else if !f.bluetooth {out[1].message="设备尚未连接到 AstroBox".into();out[1].steps=vec!["先在 AstroBox 设备页连接所选设备，再测试。".into()];}
    else if f.watch_bound==Some(false) {out[1].message="手环已解除电脑绑定".into();out[1].code=Some("WATCH_UNBOUND".into());out[1].solution=solutions("WATCH_UNBOUND");out[1].steps.clear();}
    else if f.bridge_enabled && f.http_ready && f.registered && f.launch_validated {out[1].healthy();out[1].message="双向连接正常".into();}
    else if f.test_passed {out[1].healthy();out[1].status_label=Some("测试通过".into());out[1].message="单次连接测试通过；功能仍关闭".into();}
    else if f.launch_waiting || f.registering {out[1].message="正在测试双向连接".into();}
    out[2].status="guide".into();out[2].status_label=Some("配置教程".into());
    if let Some(issue)=&f.issue {
        let id=if matches!(issue.stage.as_str(),"device"|"bridge"|"push"){"connection"}else{&issue.stage};
        if let Some(stage)=out.iter_mut().find(|s|s.id==id) {
            stage.status="red".into();stage.status_label=None;stage.message=if id=="connection"{"连接测试未通过"}else{"Hooks 接入出现问题"}.into();
            stage.code=Some(issue.code.clone());stage.native_code=issue.native_code.clone();stage.solution=solutions(&issue.code);stage.steps.clear();
        }
    }
    out
}
pub fn delivery_can_start(f:&Facts,faulted:bool)->bool {
    f.bridge_enabled && f.bound && f.bluetooth && f.watch_bound==Some(true)
        && f.http_ready && f.registered && f.launch_validated && !faulted
}
pub fn selection(manual:bool,selected:Option<&str>,stages:&[Stage],ready:bool)->Option<String> {
    if manual {if let Some(id)=selected.filter(|id|IDS.contains(id)){return Some(id.into());}}
    automatic_selection(stages,ready)
}
pub fn automatic_selection(stages:&[Stage],enabled:bool)->Option<String> {
    if stages.iter().all(|s|s.status=="green"){return None;}
    for s in stages {
        if s.status=="green" || (s.status=="guide" && enabled) {continue;}
        return Some(s.id.clone());
    }None
}

#[cfg(test)]
mod tests {
    use super::*;
    fn ready()->Facts{Facts{bound:true,bluetooth:true,watch_bound:Some(true),bridge_enabled:true,http_ready:true,registered:true,setup_ready:true,launch_validated:true,..Default::default()}}
    #[test] fn selecting_a_device_completes_configuration_without_bluetooth_or_a_running_service(){let f=Facts{bound:true,..Default::default()};let s=stages(&f);assert_eq!(s[0].status_label.as_deref(),Some("已配置"));assert_eq!(s[0].status,"green");assert_eq!(automatic_selection(&s,false).as_deref(),Some("connection"));}
    #[test] fn an_off_switch_can_show_a_completed_one_shot_test_without_enabling_delivery(){let f=Facts{bound:true,bluetooth:true,test_passed:true,..Default::default()};let s=stages(&f);assert_eq!(s[1].status_label.as_deref(),Some("测试通过"));assert!(!delivery_can_start(&f,false));assert!(s[1].message.contains("仍关闭"));}
    #[test] fn global_feature_requires_configuration_and_fresh_connection_but_not_circular_real_hook_evidence(){let mut f=ready();f.launch_validated=false;assert!(!delivery_can_start(&f,false));f.launch_validated=true;assert!(delivery_can_start(&f,false));f.bridge_enabled=false;assert!(!delivery_can_start(&f,false));f.bridge_enabled=true;assert!(!delivery_can_start(&f,true));f.setup_ready=false;assert!(delivery_can_start(&f,false));f.setup_ready=true;f.watch_bound=Some(false);assert!(!delivery_can_start(&f,false));}
    #[test] fn first_configuration_starts_with_device(){let s=stages(&Facts::default());assert_eq!(automatic_selection(&s,false).as_deref(),Some("device"));assert!(s[..2].iter().all(|s|s.status=="yellow"));assert_eq!(s[2].status,"guide");}
    #[test] fn configuration_ready_is_green_without_fabricating_execution(){let f=ready();let s=stages(&f);assert_eq!(s.len(),3);assert_eq!(s[2].status,"guide");assert_eq!(s[2].status_label.as_deref(),Some("配置教程"));assert!(!f.hook_verified);assert!(automatic_selection(&s,true).is_none());}
    #[test] fn configured_push_does_not_wait_for_first_request(){let mut f=ready();f.launch_validated=true;f.push_enabled=true;let s=stages(&f);assert!(automatic_selection(&s,true).is_none());}
    #[test] fn all_normal_has_no_selection_and_no_steps(){let mut f=ready();f.launch_validated=true;f.push_enabled=true;f.hook_verified=true;let s=stages(&f);assert!(automatic_selection(&s,true).is_none());assert!(s[..2].iter().all(|s|s.steps.is_empty()));assert!(!s[2].steps.is_empty());}
    #[test] fn confirmed_errors_keep_native_code_and_recovery_steps(){let mut f=ready();f.issue=Some(Issue{stage:"push".into(),code:"PUSH_READY_TIMEOUT".into(),message:"就绪超时".into(),native_code:None});let s=stages(&f);assert_eq!(s[1].status,"red");assert_eq!(s[1].solution.len(),2);assert!(s[1].native_code.is_none());}
    #[test] fn manual_healthy_selection_survives_refresh_until_overview(){let mut f=ready();f.hook_verified=true;f.push_enabled=true;f.launch_validated=true;let s=stages(&f);assert_eq!(selection(true,Some("connection"),&s,true).as_deref(),Some("connection"));assert!(selection(false,Some("connection"),&s,true).is_none());}
    #[test] fn device_error_blocks_downstream_without_false_red_lights(){let mut f=ready();f.issue=Some(Issue{stage:"device".into(),code:"DEVICE_DISCONNECTED".into(),message:"已断开".into(),native_code:None});let s=stages(&f);assert_eq!(s[0].status,"green");assert_eq!(s[0].status_label.as_deref(),Some("已配置"));assert_eq!(s[1].status,"red");}
    #[test] fn selected_bluetooth_device_is_not_green_until_watch_confirms_binding(){let mut f=ready();f.watch_bound=None;let s=stages(&f);assert_eq!(s[0].status,"green");assert_eq!(s[0].status_label.as_deref(),Some("已配置"));f.watch_bound=Some(false);let s=stages(&f);assert_eq!(s[0].status,"green");assert_eq!(s[1].code.as_deref(),Some("WATCH_UNBOUND"));}
    #[test] fn legacy_stop_is_unknown_not_a_valid_binding(){let mut f=ready();f.watch_bound=None;f.watch_binding_reason="legacy_stop".into();let s=stages(&f);assert_eq!(s[0].status,"green");assert!(s[0].code.is_none());}
    #[test] fn setup_reports_are_scoped_to_current_plugin_epoch(){assert!(validate_setup_report(&serde_json::json!({"epoch":"old","state":"ready"}),"new").is_err());assert!(validate_setup_report(&serde_json::json!({"epoch":"new","state":"green"}),"new").is_err());assert_eq!(validate_setup_report(&serde_json::json!({"epoch":"new","state":"ready"}),"new").unwrap(),"ready");}
    #[test] fn paused_local_forwarding_cannot_be_all_green(){let mut f=ready();f.hook_verified=true;f.hook_paused=true;f.launch_validated=true;f.push_enabled=true;let s=stages(&f);assert_eq!(s[2].status,"guide");assert!(automatic_selection(&s,true).is_none());}
    #[test] fn connection_is_independent_of_codex_setup_but_requires_the_return_path(){let mut f=ready();f.setup_ready=false;let s=stages(&f);assert_eq!(s[1].status,"green");assert_eq!(s[2].status,"guide");f.launch_validated=false;assert_eq!(stages(&f)[1].status,"yellow");}
    #[test] fn native_error_keeps_categories_without_exporting_arbitrary_text(){assert_eq!(native_error("204"),Some("204".into()));assert_eq!(native_error("permission denied: private detail"),Some("permission denied".into()));assert!(native_error("unexpected SECRET_TOKEN").is_none());}
    #[test] fn registered_interconnect_does_not_hide_an_http_start_failure(){let mut f=ready();f.http_ready=false;f.bridge_enabled=false;f.issue=Some(Issue{stage:"bridge".into(),code:"HTTP_START_FAILED".into(),message:"端口失败".into(),native_code:None});let s=stages(&f);assert_eq!(s[1].status,"red");assert_eq!(s[1].code.as_deref(),Some("HTTP_START_FAILED"));assert_eq!(s[2].status,"guide");}
}
