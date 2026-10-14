use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub mod launch;
pub mod dashboard;

pub const TIMEOUT_MS: u64 = 120_000;
pub const PAGE_CHARS: usize = 700;
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_PENDING: usize = 32;
pub const MAX_QUESTIONS: usize = 16;
/// Conservative project budget, not a claim about the host's transport limit.
pub const MAX_WATCH_FRAME_BYTES: usize = 4096;
pub const PAGE_BYTES: usize = 1024;


pub fn byte_pages(text: &str) -> Vec<String> {
    let chars:Vec<char>=text.chars().collect();
    if chars.is_empty(){return vec![String::new()];}
    chars.chunks(PAGE_CHARS).map(|chunk|chunk.iter().collect()).collect()
}

pub fn decode_interconnect(raw: &str) -> Result<(Value,bool), &'static str> {
    if raw.len()>16*1024{return Err("too_large");}
    let parsed:Value=serde_json::from_str(raw).map_err(|_|"invalid_json")?;
    let (frame,encoded)=match parsed {
        Value::String(inner)=>(serde_json::from_str::<Value>(&inner).map_err(|_|"invalid_json")?,true),
        other=>(other,false),
    };
    if !frame.is_object(){return Err("invalid_frame");}
    Ok((frame,encoded))
}

/// AstroBox 2.2.0 delivers a scoped event envelope on actual Windows hosts.
/// Keep raw-frame compatibility, but never accept another device/app envelope.
pub fn decode_interconnect_event(raw: &str, addr: &str, package: &str) -> Result<(Value,bool), &'static str> {
    let (outer,encoded)=decode_interconnect(raw)?;
    if outer.get("payloadText").is_none() {return Ok((outer,encoded));}
    if outer["addr"].as_str()!=Some(addr) || outer["pkgName"].as_str()!=Some(package) {
        return Err("event_scope_mismatch");
    }
    let text=outer["payloadText"].as_str().ok_or("invalid_event_payload")?;
    decode_interconnect(text)
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct NewRequest {
    pub id: String,
    pub kind: String,
    pub session_id: String,
    pub turn_id: String,
    pub title: String,
    pub content: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub project: String,
    #[serde(default)]
    pub presentation: String,
    #[serde(default)]
    pub lifecycle: String,
    #[serde(default)]
    pub operation: String,
    #[serde(default)]
    pub target: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Request {
    pub input: NewRequest,
    pub state: String,
    pub expires_at_ms: u64,
    pub notification_id: u32,
    pub created_at_ms: u64,
    pub resolved_by: String,
    #[serde(skip)]
    pub pages: Vec<String>,
    #[serde(skip)]
    pub reviewed: BTreeSet<usize>,
    #[serde(skip)]
    pub offered: BTreeMap<usize, String>,
}

impl Request {
    fn clear_content_cache(&mut self) {
        {
            self.input.content.clear();
            self.input.reason.clear();
            self.pages.clear();
            self.reviewed.clear();
            self.offered.clear();
            self.input.title.clear();
            self.input.project.clear();
            self.input.operation.clear();
            self.input.target.clear();
        }
    }
}

#[derive(Default)]
pub struct Bridge {
    pub enabled: bool,
    pub online: bool,
    pub device_addr: String,
    pub host_id: String,
    pub ticket: String,
    /// `None` means this plugin instance has not received a ticket-authenticated
    /// binding report from the watch. Bluetooth presence alone is not proof that
    /// the application is still bound to this computer.
    pub watch_bound: Option<bool>,
    /// A fixed protocol reason only; never store watch-supplied free text here.
    pub watch_binding_reason: String,
    pub requests: BTreeMap<String, Request>,
    pub hook_last_seen_ms: u64,
    pub permission_hook_seen: bool,
    next_notification: u32,
}

impl Bridge {
    pub fn hook_ready(&self, _now: u64) -> bool {
        // Hook inactivity is normal while the user reads or Codex is idle.
        // Connection liveness is independently checked by the transport.
        self.permission_hook_seen && self.hook_last_seen_ms!=0
    }
    pub fn record_hook(&mut self, event: &str, now: u64) -> bool {
        if !matches!(event,"PermissionRequest"|"PreToolUse"|"PostToolUse"|"UserPromptSubmit"|"Interrupt"|"SessionEnd") {return false;}
        self.hook_last_seen_ms=now;
        if event=="PermissionRequest" {self.permission_hook_seen=true;}
        true
    }
    pub fn expire(&mut self, now: u64) -> Vec<u32> {
        let mut removed = Vec::new();
        for request in self.requests.values_mut() {
            if request.state == "pending" && request.expires_at_ms != 0 && now >= request.expires_at_ms {
                request.state = "expired".into();
                request.reviewed.clear();
                request.clear_content_cache();
                removed.push(request.notification_id);
            }
        }
        // Terminal records survive briefly so polling hooks can observe the result.
        self.requests
            .retain(|_, request| request.state == "pending" || now < request.expires_at_ms.saturating_add(60_000));
        removed
    }

    pub fn suspend(&mut self, state: &str) -> Vec<u32> {
        self.ticket.clear();
        let mut removed = Vec::new();
        for request in self.requests.values_mut() {
            if request.state == "pending" {
                request.state = state.into();
                request.reviewed.clear();
                request.clear_content_cache();
                removed.push(request.notification_id);
            }
        }
        removed
    }

    pub fn set_online(&mut self, online: bool) -> Vec<u32> {
        self.online = online;
        if online {
            Vec::new()
        } else {
            self.suspend("unavailable")
        }
    }

    pub fn create(&mut self, input: NewRequest, now: u64) -> Result<(u32, bool), &'static str> {
        self.expire(now);
        if !self.enabled || !self.online || self.device_addr.is_empty() || self.watch_bound != Some(true) {
            return Err("unavailable");
        }
        if input.id.is_empty()
            || input.id.len() > 128
            || !input
                .id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
            || input.session_id.is_empty()
            || input.session_id.len() > 256
            || input.turn_id.len() > 256
            || input.title.len() > 512
            || !matches!(input.kind.as_str(), "approval" | "question" | "probe")
            || input.content.len() > MAX_REQUEST_BYTES
            || input.reason.len() > MAX_REQUEST_BYTES
            || input.project.len() > 512
            || input.operation.len() > 256 || input.target.len() > 512
            || !matches!(input.presentation.as_str(), "" | "human")
            || !matches!(input.lifecycle.as_str(), "" | "hook")
        {
            return Err("invalid_request");
        }
        if let Some(existing) = self.requests.get(&input.id) {
            if existing.input.session_id == input.session_id
                && existing.input.content == input.content
                && existing.input.kind == input.kind
                && existing.input.turn_id == input.turn_id
                && existing.input.reason == input.reason
                && existing.input.presentation == input.presentation
                && existing.input.project == input.project
                && existing.input.lifecycle == input.lifecycle
                && existing.input.operation == input.operation && existing.input.target == input.target
            {
                return Ok((existing.notification_id, false));
            }
            return Err("id_conflict");
        }
        if self
            .requests
            .values()
            .filter(|r| r.state == "pending")
            .count()
            >= MAX_PENDING
        {
            return Err("queue_full");
        }
        self.next_notification = self.next_notification.wrapping_add(1).max(1);
        let notification_id = self.next_notification;
        let display = if input.kind == "approval" {
            if input.reason.is_empty() { "Codex 请求批准一次操作。" } else { &input.reason }
        } else { &input.content };
        let pages = byte_pages(display);

        let expires_at_ms = if input.lifecycle == "hook" { if input.kind == "approval" { now + 15_000 } else { 0 } } else { now + TIMEOUT_MS };
        self.requests.insert(
            input.id.clone(),
            Request {
                input,
                state: "pending".into(),
                expires_at_ms,
                notification_id,
                created_at_ms: now,
                resolved_by: String::new(),
                pages: if pages.is_empty() {
                    vec![String::new()]
                } else {
                    pages
                },
                reviewed: BTreeSet::new(),
                offered: BTreeMap::new(),
            },
        );
        Ok((notification_id, true))
    }

    pub fn cancel(&mut self, id: &str) -> Option<u32> {
        let request = self.requests.get_mut(id)?;
        if request.state == "pending" {
            request.state = "cancelled".into();
            request.reviewed.clear();
        }
        request.clear_content_cache();
        Some(request.notification_id)
    }

    pub fn summaries(&self) -> Vec<Value> {
        self.requests.values().filter(|r| r.state == "pending").map(|r| json!({
            "id": r.input.id, "kind": r.input.kind, "title": r.input.title,
            "session": r.input.session_id, "expiresAt": if r.input.lifecycle == "hook" { Value::Null } else { json!(r.expires_at_ms) }, "pages": r.pages.len(),
            "project":r.input.project,"createdAt":r.created_at_ms,
        })).collect()
    }

    pub fn renew_hook(&mut self, id: &str, now: u64) {
        if let Some(r) = self.requests.get_mut(id) {
            if r.state == "pending" && r.input.lifecycle == "hook" && r.input.kind == "approval" {
                r.expires_at_ms = now + 15_000;
                self.hook_last_seen_ms=now;
            }
        }
    }

    pub fn watch_list(&self, _cursor:&str) -> (Vec<Value>, String) {
        (self.summaries(),String::new())
    }

    pub fn desktop_decision(&mut self, id: &str, session: &str, decision: &str, now: u64) -> Result<Value, &'static str> {
        self.expire(now);
        let r = self.requests.get_mut(id).ok_or("not_found")?;
        if r.input.session_id != session || r.input.kind != "approval" || !matches!(decision,"allow"|"deny") {
            return Err("invalid_decision");
        }
        if r.state == "pending" {
            if !self.enabled || !self.online { return Err("unavailable"); }
            r.state = decision.into();
            r.resolved_by = "desktop".into();
            r.clear_content_cache();
        }
        Ok(json!({"id":id,"session_id":session,"state":r.state,"resolvedBy":r.resolved_by}))
    }

    pub fn watch_message(&mut self, message: &Value, now: u64, new_ticket: &str) -> Value {
        self.expire(now);
        let command = message["type"].as_str().unwrap_or("");
        if message["v"].as_u64() != Some(1) {
            return json!({"v":1,"type":"error","error":"version"});
        }
        if !self.online {
            return json!({"v":1,"type":"unavailable"});
        }
        if command == "hello" {
            // The pre-UI watch has no separate binding/capability packet.
            self.watch_bound=Some(true);self.watch_binding_reason="legacy_hello".into();
            self.ticket = new_ticket.into();
            for request in self.requests.values_mut() {
                request.reviewed.clear();
                request.offered.clear();
            }
            let (rows,next)=self.watch_list("");
            return json!({"v":1,"type":"hello","hostId":self.host_id,"ticket":self.ticket,
                "enabled":self.enabled,"requests":rows,"nextCursor":next,"serverTime":now,"hookReady":self.hook_ready(now),"experimentalAudioValidated":false});
        }
        if self.ticket.is_empty() || message["ticket"].as_str() != Some(self.ticket.as_str()) {
            return json!({"v":1,"type":"error","error":"invalid_ticket"});
        }
        // Binding is deliberately a separate, ticket-authenticated report. A
        // hello only establishes a fresh session ticket; it cannot turn a prior
        // user-initiated unbind back into a green device state.
        if command == "binding" {
            let Some(bound)=message["bound"].as_bool() else {
                return json!({"v":1,"type":"error","error":"invalid_binding"});
            };
            let reason=match message["reason"].as_str() {
                Some("user_unbound")=>"user_unbound",
                Some("watch_bound")=>"watch_bound",
                Some("app_stopped")=>"app_stopped",
                _=>"binding_confirmed",
            };
            self.watch_bound=Some(bound);
            self.watch_binding_reason=reason.into();
            if !bound {
                let ticket=self.ticket.clone();
                self.enabled=false;
                self.suspend("unavailable");
                return json!({"v":1,"type":"binding","ticket":ticket,"bound":false,"reason":reason,"enabled":false});
            }
            return json!({"v":1,"type":"binding","ticket":self.ticket,"bound":true,"reason":reason,"enabled":self.enabled});
        }
        if command == "resume" && message["manual"].as_bool() == Some(true) {
            if self.watch_bound != Some(true) {
                return json!({"v":1,"type":"error","error":"binding_unconfirmed"});
            }
            self.enabled = true;
            let (rows,next)=self.watch_list("");
            return json!({"v":1,"type":"resumed","ticket":self.ticket,"requests":rows,"nextCursor":next,"serverTime":now,"hookReady":self.hook_ready(now),"enabled":self.enabled});
        }
        if !self.enabled {
            return json!({"v":1,"type":"unavailable"});
        }
        if command == "ping" {
            return json!({"v":1,"type":"pong","nonce":message["nonce"],"ticket":self.ticket,"serverTime":now});
        }
        if command == "list" {
            let cursor=message["cursor"].as_str().unwrap_or("");
            let (rows,next)=self.watch_list(cursor);
            let resolved:Vec<Value> = self.requests.values().filter(|r|r.resolved_by=="desktop").take(4).map(|r|json!({"id":r.input.id,"state":r.state,"source":"desktop"})).collect();
            return json!({"v":1,"type":"list","ticket":self.ticket,"requests":rows,"cursor":cursor,"nextCursor":next,"resolved":resolved,"serverTime":now,"hookReady":self.hook_ready(now),"enabled":self.enabled});
        }
        if command == "stop" {
            let reason=match message["reason"].as_str() {
                Some("app_stopped")=>"app_stopped",
                Some("user_unbound")=>"user_unbound",
                // The pre-2.0 watch sent a bare stop when it was closed or
                // unbound. Keep that old packet compatible, but treat it as
                // unknown rather than claiming a still-valid binding.
                _=>"legacy_stop",
            };
            self.watch_binding_reason=reason.into();
            self.watch_bound=match reason {
                "user_unbound"=>Some(false),
                "app_stopped"=>self.watch_bound,
                _=>None,
            };
            self.enabled = false;
            self.suspend("unavailable");
            return json!({"v":1,"type":"stopped","reason":reason});
        }
        let id = message["id"].as_str().unwrap_or("");
        let Some(request) = self.requests.get_mut(id) else {
            return json!({"v":1,"type":"error","id":id,"error":"not_found"});
        };
        if request.state != "pending" {
            return json!({"v":1,"type":"result","ticket":self.ticket,"id":id,"state":request.state,"source":request.resolved_by});
        }
        if command == "detail" {
            let Some(page) = message["page"].as_u64().map(|p| p as usize) else {
                return json!({"v":1,"type":"error","id":id,"error":"invalid_page"});
            };
            if page >= request.pages.len() {
                return json!({"v":1,"type":"error","id":id,"error":"invalid_page"});
            }
            let seq=message["seq"].as_u64().unwrap_or(0);


            return json!({"v":1,"type":"detail","ticket":self.ticket,"id":id,"kind":request.input.kind,
                "title":request.input.title,"session":request.input.session_id,"content":request.pages[page],
                "project":request.input.project,"operation":request.input.operation,"target":request.input.target,
                "seq":seq,
                "desktopRequired":false,
                "page":page,"pages":request.pages.len(),"expiresAt":if request.input.lifecycle=="hook" {Value::Null} else {json!(request.expires_at_ms)},
                "presentation":request.input.presentation,
                "serverTime":now,"canApprove":request.input.kind=="approval"});
        }
        if command == "decision" {
            let decision = message["decision"].as_str().unwrap_or("");
            if request.input.kind != "approval" || !matches!(decision, "allow" | "deny") {
                return json!({"v":1,"type":"error","id":id,"error":"invalid_decision"});
            }
            request.state = decision.into();
            request.resolved_by = "watch".into();
            request.clear_content_cache();
            return json!({"v":1,"type":"result","ticket":self.ticket,"id":id,"state":request.state,"source":request.resolved_by});
        }
        json!({"v":1,"type":"error","id":id,"error":"unknown_command"})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn wire_budget_and_utf8_roundtrip_include_emoji_and_escaped_controls() {
        for text in ["中文🛰️\\\"\n".repeat(1000),"x".repeat(MAX_REQUEST_BYTES),"测".repeat(10000)] {
            let pages=byte_pages(&text);assert_eq!(pages.concat(),text);
            for page in &pages {assert!(serde_json::to_string(page).unwrap().len()<=PAGE_BYTES);}
        }
        let mut bridge=setup();let mut req=input("long");req.presentation="human".into();req.reason="测".repeat(10000);
        bridge.create(req,100).unwrap();bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        for page in 0..bridge.requests["long"].pages.len() {
            let frame=bridge.watch_message(&json!({"v":1,"type":"detail","ticket":"ticket","id":"long","page":page,"seq":page}),102,"unused");
            assert!(frame.get("reason").is_none());assert!(frame.to_string().len()<MAX_WATCH_FRAME_BYTES);assert_eq!(frame["canApprove"],true);
        }
    }
    #[test]
    fn question_capacity_and_orphan_recovery_cannot_starve_approvals() {
        let mut bridge=setup();
        for n in 0..MAX_QUESTIONS {let mut r=input(&format!("q{n}"));r.kind="question".into();r.lifecycle="hook".into();bridge.create(r,100).unwrap();}
        assert!(bridge.create(input("approval"),101).is_ok());
        bridge.renew_session("session1",QUESTION_LEASE_MS-100);
        bridge.expire(QUESTION_LEASE_MS+100);assert_eq!(bridge.requests["q0"].state,"pending");
        bridge.expire(QUESTION_LEASE_MS*2);assert!(!bridge.requests.values().any(|r|r.state=="pending"));
    }
    #[test]
    fn list_cursor_transmits_every_id_with_a_bounded_budget() {
        let mut bridge=setup();for n in 0..MAX_PENDING {let mut r=input(&format!("a{n:02}"));r.title="测".repeat(160);r.project="项目".repeat(80);bridge.create(r,100).unwrap();}
        let mut cursor=String::new();let mut ids=BTreeSet::new();
        loop {let (rows,next)=bridge.watch_list(&cursor);assert!(json!(rows).to_string().len()<=2048);for r in rows{ids.insert(r["id"].as_str().unwrap().to_string());}if next.is_empty(){break;}assert!(next>cursor);cursor=next;}
        assert_eq!(ids.len(),MAX_PENDING);
    }
    #[test]
    fn page_read_requires_an_offered_page_in_the_current_ticket() {
        let mut bridge=setup();bridge.create(input("a"),100).unwrap();bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        let ack=json!({"v":1,"type":"page_read","ticket":"ticket","id":"a","page":0,"readToken":"forged"});
        assert_eq!(bridge.watch_message(&ack,102,"unused")["error"],"page_not_offered");
        assert!(bridge.requests["a"].reviewed.is_empty());
    }
    #[test]
    fn windows_interconnect_envelope_decodes_and_establishes_handshake() {
        let frame=json!({"v":1,"type":"hello"});
        let envelope=json!({"addr":"band11","pkgName":"com.local.codexband","payloadHex":"ignored","payloadText":frame.to_string()});
        let (decoded,_)=decode_interconnect_event(&envelope.to_string(),"band11","com.local.codexband").unwrap();
        let mut bridge=setup();
        let response=bridge.watch_message(&decoded,100,"fresh-ticket");
        assert_eq!(response["type"],"hello");
        assert_eq!(bridge.ticket,"fresh-ticket");
        assert_eq!(decode_interconnect_event(&frame.to_string(),"band11","com.local.codexband").unwrap().0,frame);
    }
    #[test]
    fn windows_envelope_rejects_wrong_scope_or_non_text_payload() {
        for (addr,pkg,text) in [("other","com.local.codexband",json!("{}")),("band11","other",json!("{}")),("band11","com.local.codexband",json!({"v":1,"type":"hello"}))] {
            let envelope=json!({"addr":addr,"pkgName":pkg,"payloadText":text});
            assert!(decode_interconnect_event(&envelope.to_string(),"band11","com.local.codexband").is_err());
        }
        let envelope=json!({"addr":"band11","pkgName":"com.local.codexband","payloadText":"x".repeat(16385)});
        assert_eq!(decode_interconnect_event(&envelope.to_string(),"band11","com.local.codexband"),Err("too_large"));
    }
    #[test]
    fn interconnect_accepts_an_object_or_a_single_legacy_string_encoding() {
        let raw=r#"{"v":1,"type":"hello"}"#;
        assert_eq!(decode_interconnect(raw).unwrap().0["type"],"hello");
        let legacy=serde_json::to_string(raw).unwrap();assert!(decode_interconnect(&legacy).unwrap().1);
        assert_eq!(decode_interconnect(&legacy).unwrap().0["v"],1);
        assert!(decode_interconnect(&serde_json::to_string(&legacy).unwrap()).is_err());
        assert!(decode_interconnect("[]").is_err());
    }
    fn setup() -> Bridge {
        Bridge {
            enabled: true,
            online: true,
            device_addr: "band11".into(),
            host_id: "pc".into(),
            watch_bound: Some(true),
            watch_binding_reason: "watch_bound".into(),
            ..Bridge::default()
        }
    }
    fn input(id: &str) -> NewRequest {
        NewRequest {
            id: id.into(),
            kind: "approval".into(),
            session_id: "session1".into(),
            turn_id: "turn1".into(),
            title: "请求批准".into(),
            content: "测".repeat(1500),
            reason: "验证完整请求后才能批准".into(),
            project: String::new(), presentation: String::new(), lifecycle: String::new(), operation: "测试".into(), target: "本机".into(),
        }
    }
    fn message(command: &str) -> Value {
        json!({"v":1,"type":command,"ticket":"ticket","id":"a"})
    }
    #[test]
    fn health_requires_permission_hook_but_idle_is_not_failure() {
        let mut bridge=setup();assert!(!bridge.hook_ready(100));
        assert!(bridge.record_hook("PreToolUse",100));assert!(!bridge.hook_ready(101));
        assert!(!bridge.record_hook("forged",102));
        assert!(bridge.record_hook("PermissionRequest",103));assert!(bridge.hook_ready(104));
        assert!(bridge.hook_ready(90_104));
        bridge.record_hook("PreToolUse",90_105);assert!(bridge.hook_ready(90_106));
    }
    #[test]
    fn desktop_and_watch_first_decision_wins_and_discards_all_content() {
        let mut bridge=setup();bridge.create(input("a"),100).unwrap();
        bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        assert!(bridge.desktop_decision("a","wrong","allow",102).is_err());
        assert_eq!(bridge.desktop_decision("a","session1","deny",103).unwrap()["state"],"deny");
        assert!(bridge.requests["a"].input.content.is_empty());
        assert!(bridge.requests["a"].input.reason.is_empty());
        assert!(bridge.requests["a"].pages.is_empty());
        let result=bridge.watch_message(&json!({"v":1,"type":"decision","ticket":"ticket","id":"a","decision":"allow"}),104,"unused");
        assert_eq!(result["state"],"deny");
        assert_eq!(result["source"],"desktop");
        assert_eq!(bridge.desktop_decision("a","session1","allow",105).unwrap()["state"],"deny");
        assert_eq!(bridge.watch_message(&json!({"v":1,"type":"list","ticket":"ticket"}),106,"unused")["resolved"][0]["source"],"desktop");
    }
    #[test]
    fn hook_lease_follows_owner_not_a_120_second_watch_deadline() {
        let mut bridge=setup();let mut request=input("a");request.lifecycle="hook".into();
        bridge.create(request,100).unwrap();
        for time in (100..300_000).step_by(10_000) {bridge.expire(time);bridge.renew_hook("a",time);}
        assert_eq!(bridge.requests["a"].state,"pending");
        assert!(bridge.summaries()[0]["expiresAt"].is_null());
        bridge.expire(320_000);assert_eq!(bridge.requests["a"].state,"expired");
        assert!(bridge.requests["a"].input.content.is_empty());
    }
    #[test]
    fn human_approval_pages_never_contain_technical_payload() {
        let mut bridge=setup();let mut request=input("a");request.presentation="human".into();
        request.reason="完整请求说明".repeat(200);let expected=request.reason.clone();
        bridge.create(request,100).unwrap();
        assert_eq!(bridge.requests["a"].pages.concat(),expected);
        assert_eq!(bridge.summaries()[0]["createdAt"],100);
    }
    #[test]
    fn request_with_missing_reason_uses_a_summary_and_can_be_decided() {
        let mut bridge=setup();let mut request=input("a");request.presentation="human".into();request.reason.clear();
        bridge.create(request,100).unwrap();bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        let detail=bridge.watch_message(&json!({"v":1,"type":"detail","id":"a","page":0,"ticket":"ticket"}),102,"unused");
        assert_eq!(detail["canApprove"],true);assert!(!detail["content"].as_str().unwrap().contains("测"));
        assert_eq!(bridge.watch_message(&json!({"v":1,"type":"decision","id":"a","decision":"allow","ticket":"ticket"}),103,"unused")["state"],"allow");
    }
    #[test]
    fn unread_pages_do_not_block_approval_and_first_decision_still_wins() {
        let mut bridge=setup();let mut request=input("a");request.reason="请求说明".repeat(1000);
        bridge.create(request,100).unwrap();bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        assert!(bridge.requests["a"].pages.len()>1);
        assert!(bridge.requests["a"].reviewed.is_empty());
        let mut decide=message("decision");decide["decision"]=json!("allow");
        assert_eq!(bridge.watch_message(&decide,102,"unused")["state"],"allow");
        decide["decision"]=json!("deny");assert_eq!(bridge.watch_message(&decide,103,"unused")["state"],"allow");
    }
    #[test]
    fn stale_and_cross_connection_decisions_fail() {
        let mut bridge = setup();
        bridge.create(input("a"), 100).unwrap();
        bridge.watch_message(&json!({"v":1,"type":"hello"}), 101, "ticket");
        let mut decide = message("decision");
        decide["decision"] = json!("deny");
        decide["ticket"] = json!("forged");
        assert_eq!(
            bridge.watch_message(&decide, 102, "unused")["error"],
            "invalid_ticket"
        );
        decide["ticket"] = json!("ticket");
        assert_eq!(
            bridge.watch_message(&decide, 120100, "unused")["state"],
            "expired"
        );
    }
    #[test]
    fn disconnect_stop_and_cancel_never_allow() {
        let mut bridge = setup();
        bridge.create(input("a"), 100).unwrap();
        bridge.set_online(false);
        assert_eq!(bridge.requests["a"].state, "unavailable");
        assert!(bridge.create(input("b"), 101).is_err());
        bridge.set_online(true);
        bridge.create(input("b"), 102).unwrap();
        bridge.cancel("b");
        assert_eq!(bridge.requests["b"].state, "cancelled");
        bridge.create(input("c"), 103).unwrap();
        bridge.watch_message(&json!({"v":1,"type":"hello"}), 104, "ticket");
        bridge.watch_message(&message("stop"), 105, "unused");
        assert!(!bridge.enabled);
        assert_eq!(bridge.requests["c"].state, "unavailable");
    }
    #[test]
    fn unique_ids_and_bounded_queue() {
        let mut bridge = setup();
        bridge.create(input("a"), 100).unwrap();
        assert!(!bridge.create(input("a"), 101).unwrap().1);
        let mut conflict = input("a");
        conflict.session_id = "other".into();
        assert_eq!(bridge.create(conflict, 102).unwrap_err(), "id_conflict");
        for number in 1..MAX_PENDING {
            bridge.create(input(&number.to_string()), 103).unwrap();
        }
        assert_eq!(
            bridge.create(input("overflow"), 104).unwrap_err(),
            "queue_full"
        );
        bridge.expire(120104);
        assert!(bridge.create(input("fresh"), 120105).is_ok());
    }
    #[test]
    fn answered_question_discards_body_and_returns_a_valid_terminal_frame() {
        let mut bridge = setup();
        let mut question=input("question");question.kind="question".into();
        bridge.create(question,100).unwrap();bridge.create(input("approval"),100).unwrap();
        bridge.watch_message(&json!({"v":1,"type":"hello"}),101,"ticket");
        bridge.cancel("question");
        let cleared=&bridge.requests["question"];
        assert!(cleared.input.content.is_empty() && cleared.input.reason.is_empty() && cleared.pages.is_empty());
        assert_eq!(bridge.summaries().len(),1);
        assert_eq!(bridge.requests["approval"].state,"pending");
        let frame=bridge.watch_message(&json!({"v":1,"type":"detail","ticket":"ticket","id":"question","page":0}),102,"unused");
        assert_eq!(frame["ticket"],"ticket");assert_eq!(frame["state"],"cancelled");
    }
    #[test]
    fn stopping_cannot_be_undone_by_a_reconnect() {
        let mut bridge = setup();
        bridge.watch_message(&json!({"v":1,"type":"hello"}), 100, "ticket");
        bridge.watch_message(&message("stop"), 101, "unused");
        bridge.watch_message(&json!({"v":1,"type":"hello"}), 102, "new-ticket");
        assert!(!bridge.enabled);
        bridge.watch_message(
            &json!({"v":1,"type":"resume","ticket":"new-ticket","manual":false}),
            103,
            "unused",
        );
        assert!(!bridge.enabled);
        bridge.watch_message(
            &json!({"v":1,"type":"binding","ticket":"new-ticket","bound":true,"reason":"watch_bound"}),
            104,
            "unused",
        );
        bridge.watch_message(
            &json!({"v":1,"type":"resume","ticket":"new-ticket","manual":true}),
            105,
            "unused",
        );
        assert!(bridge.enabled);
    }
    #[test]
    fn binding_requires_the_fresh_ticket_and_unbind_clears_the_delivery_path() {
        let mut bridge=setup();
        bridge.watch_message(&json!({"v":1,"type":"hello"}),100,"ticket");
        let forged=bridge.watch_message(&json!({"v":1,"type":"binding","ticket":"wrong","bound":false,"reason":"user_unbound"}),101,"unused");
        assert_eq!(forged["error"],"invalid_ticket");
        let result=bridge.watch_message(&json!({"v":1,"type":"binding","ticket":"ticket","bound":false,"reason":"user_unbound"}),102,"unused");
        assert_eq!(result["type"],"binding");assert_eq!(result["bound"],false);
        assert_eq!(bridge.watch_bound,Some(false));assert_eq!(bridge.watch_binding_reason,"user_unbound");
        assert!(!bridge.enabled);assert!(bridge.ticket.is_empty());assert!(bridge.create(input("after-unbind"),103).is_err());
    }
    #[test]
    fn legacy_stop_never_claims_a_valid_watch_binding() {
        let mut bridge=setup();bridge.watch_message(&json!({"v":1,"type":"hello"}),100,"ticket");
        let result=bridge.watch_message(&json!({"v":1,"type":"stop","ticket":"ticket"}),101,"unused");
        assert_eq!(result["reason"],"legacy_stop");assert_eq!(bridge.watch_bound,None);
    }
}
