use std::collections::BTreeSet;

#[derive(Default)]
pub struct LaunchDelivery {
    pub queued: BTreeSet<String>,
    pub delivered: BTreeSet<String>,
    pub nonce: String,
    pub deadline: u64,
    pub waiting: bool,
    pub faulted: bool,
    pub probe: bool,
}
impl LaunchDelivery {
    pub fn queue(&mut self, id: &str) { self.queued.insert(id.into()); }
    pub fn begin(&mut self, nonce: String, now: u64, probe: bool) -> bool {
        if self.faulted || !self.nonce.is_empty() || (!probe && self.queued.is_empty()) {return false;}
        self.nonce=nonce;self.deadline=now+20_000;self.waiting=false;self.probe=probe;true
    }
    pub fn launched(&mut self) {if !self.nonce.is_empty(){self.waiting=true;}}
    pub fn ready(&mut self, nonce: &str, now: u64, authenticated: bool, visible: bool) -> Option<Vec<String>> {
        if !authenticated || !visible || !self.waiting || self.nonce!=nonce || nonce.is_empty() || now>=self.deadline {return None;}
        let ids=self.queued.iter().cloned().collect::<Vec<_>>();
        self.delivered.extend(ids.iter().cloned());self.queued.clear();self.nonce.clear();self.waiting=false;self.deadline=0;
        Some(ids)
    }
    pub fn prune(&mut self, pending: &BTreeSet<String>) {
        self.queued.retain(|id|pending.contains(id));self.delivered.retain(|id|pending.contains(id));
        if self.queued.is_empty() && !self.probe {self.nonce.clear();self.waiting=false;self.deadline=0;}
    }
    pub fn fail(&mut self) {self.faulted=true;self.queued.clear();self.delivered.clear();self.nonce.clear();self.waiting=false;self.deadline=0;self.probe=false;}
    pub fn expired(&self, now:u64)->bool {!self.nonce.is_empty() && now>=self.deadline}
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn reconnect_retries_are_bounded_and_the_off_switch_wins() {
        let mut next=3000;let mut attempts=0;
        assert_eq!(reconnect_due(true,false,false,false,next,attempts,3000),(false,3000,0));
        for now in [3000,6000,16000] {
            let (due,n,a)=reconnect_due(true,true,false,false,next,attempts,now);assert!(due);next=n;attempts=a;
        }
        assert_eq!(reconnect_due(true,true,false,false,next,attempts,46000),(false,0,3));
        assert_eq!(reconnect_due(false,true,false,false,3000,1,10000),(false,0,0));
        assert_eq!(reconnect_due(true,true,false,true,3000,2,10000),(false,0,0));
    }
    #[test] fn recovery_waits_for_the_current_probe_instead_of_overlapping_launches() {
        assert_eq!(reconnect_due(true,true,true,false,1000,1,25000),(false,1000,1));
        let mut d=LaunchDelivery::default();d.fail();d=LaunchDelivery::default();
        assert!(d.begin("fresh-reconnect".into(),10000,true));d.launched();
        assert!(d.ready("old-before-disconnect",10001,true,true).is_none());
        assert!(d.ready("fresh-reconnect",10001,false,true).is_none());
        assert_eq!(d.ready("fresh-reconnect",10002,true,true),Some(vec![]));
    }
    #[test] fn readiness_requires_launch_complete_nonce_ticket_and_foreground() {
        let mut d=LaunchDelivery::default();d.queue("one");assert!(d.begin("fresh".into(),100,false));
        assert!(d.ready("fresh",101,true,true).is_none());d.launched();
        assert!(d.ready("old",102,true,true).is_none());assert!(d.ready("fresh",102,false,true).is_none());assert!(d.ready("fresh",102,true,false).is_none());
        assert_eq!(d.ready("fresh",103,true,true),Some(vec!["one".into()]));assert!(d.ready("fresh",104,true,true).is_none());
    }
    #[test] fn desktop_resolution_and_expiry_never_deliver_stale_requests() {
        let mut d=LaunchDelivery::default();d.queue("one");d.queue("two");d.begin("fresh".into(),100,false);d.launched();d.prune(&BTreeSet::from(["two".into()]));
        assert_eq!(d.ready("fresh",101,true,true),Some(vec!["two".into()]));d.prune(&BTreeSet::new());assert!(d.delivered.is_empty());
        d.queue("expired");d.begin("next".into(),200,false);d.launched();assert!(d.ready("next",20200,true,true).is_none());
    }
    #[test] fn disconnect_failure_blocks_automatic_retry_and_probe_is_empty() {
        let mut d=LaunchDelivery::default();assert!(d.begin("test".into(),0,true));d.launched();assert_eq!(d.ready("test",1,true,true),Some(vec![]));
        d.fail();d.queue("new");assert!(!d.begin("again".into(),2,false));
    }
}
