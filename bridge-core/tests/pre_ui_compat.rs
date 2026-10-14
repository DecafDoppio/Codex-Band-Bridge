use bridge_core::{Bridge,NewRequest};
use serde_json::json;

fn connected() -> Bridge {
    let mut b=Bridge::default();b.enabled=true;b.online=true;
    b.device_addr="selected-device".into();b.host_id="existing-pc".into();
    let reply=b.watch_message(&json!({"v":1,"type":"hello","firmware":"4.100.139","visible":true}),100,"ticket");
    assert_eq!(reply["type"],"hello");
    b
}
fn request(id:&str,kind:&str)->NewRequest {
    serde_json::from_value(json!({"id":id,"kind":kind,"session_id":"session","turn_id":"turn",
        "title":"请求批准","content":"operation payload","reason":"只读取时间","presentation":"human","lifecycle":"hook"})).unwrap()
}

#[test]
fn pre_ui_hello_and_approval_need_no_new_capabilities_or_read_receipts() {
    let mut b=connected();b.create(request("one","approval"),101).unwrap();
    let page=b.watch_message(&json!({"v":1,"type":"detail","ticket":"ticket","id":"one","page":0}),102,"unused");
    assert_eq!(page["content"],"只读取时间");assert_eq!(page["canApprove"],true);
    assert!(page.get("readToken").is_none());
    let reply=b.watch_message(&json!({"v":1,"type":"decision","ticket":"ticket","id":"one","decision":"allow"}),103,"unused");
    assert_eq!(reply["state"],"allow");
}

#[test]
fn pre_ui_list_without_cursor_has_the_whole_queue_and_preserves_first_decision() {
    let mut b=connected();for id in ["a","b","c"]{b.create(request(id,"approval"),101).unwrap();}
    let list=b.watch_message(&json!({"v":1,"type":"list","ticket":"ticket"}),102,"unused");
    assert_eq!(list["requests"].as_array().unwrap().len(),3);
    assert_eq!(list["nextCursor"],"");
    b.desktop_decision("b","session","deny",103).unwrap();
    let reply=b.watch_message(&json!({"v":1,"type":"decision","ticket":"ticket","id":"b","decision":"allow"}),104,"unused");
    assert_eq!(reply["state"],"deny");
    let bad=b.watch_message(&json!({"v":1,"type":"decision","ticket":"wrong","id":"a","decision":"allow"}),105,"unused");
    assert_eq!(bad["error"],"invalid_ticket");
}

#[test]
fn questions_use_the_baseline_lifecycle_without_a_new_background_lease() {
    let mut b=connected();b.create(request("q","question"),101).unwrap();
    b.expire(2*24*60*60*1000);
    assert_eq!(b.requests["q"].state,"pending");
    b.cancel("q");assert_eq!(b.requests["q"].state,"cancelled");
}
