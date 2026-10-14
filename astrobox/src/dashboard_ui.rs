use crate::astrobox::psys_host_v4::ui::{self, Element, ElementType, FlexDirection, Event};
use bridge_core::dashboard::Stage;

const BG:&str="#24272D";
const TEXT:&str="#F0F0F2";
const MUTED:&str="#B0B4BD";
fn text(value:&str)->Element {Element::new(ElementType::P,Some(value)).text_color(TEXT).margin(0)}
fn button(label:&str,id:&str)->Element {Element::new(ElementType::Button,Some(label)).without_default_styles()
    .padding(12).radius(12).bg("#3D4652").text_color(TEXT).border(1,"#566172").on(Event::Click,id)}
fn label(action:&str)->&str{match action {
    "refresh"=>"刷新设备","start"=>"启动桥接","stop"=>"停止桥接",
    "launch_probe"=>"仅测试连接",_=>action}}
fn device_picker(devices:&[(String,String)],bound_addr:&str)->Element {
    let mut candidates=Element::new(ElementType::Div,None).flex().flex_direction(FlexDirection::Column).gap(8).flex_grow(1.0);
    if devices.is_empty(){candidates=candidates.child(text("未发现设备，请先在 AstroBox 设备页连接手环。").text_color(MUTED));}
    for (name,addr) in devices {
        let suffix=addr.get(addr.len().saturating_sub(5)..).unwrap_or(addr);
        let chosen=addr==bound_addr;
        let mark=Element::new(ElementType::Div,None).width(20).height(20).radius(10)
            .border(2,if chosen{"#83B69B"}else{"#77818F"}).flex().align_center().justify_center()
            .child(Element::new(ElementType::Div,None).width(10).height(10).radius(5).bg(if chosen{"#83B69B"}else{BG}));
        candidates=candidates.child(Element::new(ElementType::Button,None).without_default_styles()
            .padding(12).radius(12).bg(if chosen{"#394453"}else{"#30343C"}).border(1,if chosen{"#83B69B"}else{"#566172"})
            .flex().align_center().gap(12).on(Event::Click,&format!("bind:{addr}"))
            .child(mark).child(text(&format!("{name} · {suffix}"))));
    }
    Element::new(ElementType::Div,None).flex().align_center().gap(12)
        .child(button("刷新设备","refresh")).child(candidates)
}

pub fn render(id:&str,stages:&[Stage],selected:Option<&str>,devices:&[(String,String)],width:u32,notice:&str,enabled:bool,bound_addr:&str,diagnostics:bool,epoch:&str,rejected:bool) {
    let mut root=Element::new(ElementType::Div,None).relative().width_full().min_height(640)
        .bg("#30343C").padding(28).flex().flex_direction(FlexDirection::Column).gap(24);
    let bg=include_str!("../../assets/brand/background.dataurl");
    root=root.child(Element::new(ElementType::Image,Some(bg)).prop("src",bg).absolute()
        .top(0).left(0).width_full().height_full().opacity(0.8).z_index(0));
    let icon=include_str!("../../assets/brand/icon.dataurl");
    let header=Element::new(ElementType::Div,None).relative().z_index(1).flex().align_center().gap(16)
        .child(Element::new(ElementType::Image,Some(icon)).prop("src",icon).width(48).height(48).radius(12))
        .child(text("Codex Band Bridge")).child(text(env!("CARGO_PKG_VERSION")).text_color(MUTED));
    root=root.child(header);
    let thumb=if rejected {Element::new(ElementType::Image,Some(include_str!("../../assets/brand/power-reject.dataurl"))).prop("src",include_str!("../../assets/brand/power-reject.dataurl")).absolute().top(0).left(0).width(64).height(34)} else {Element::new(ElementType::Div,None).absolute().top(4).left(if enabled{34}else{4}).transition("left 180ms ease-out").width(26).height(26).radius(13).bg(TEXT)};
    let power=Element::new(ElementType::Div,None).relative().z_index(1).width_full().padding(24).radius(20).bg(BG).border(1,"#454A55").flex().align_center().gap(12)
        .child(text("启动 Codex Connector").size(24).flex_grow(1.0))
        .child(text(if enabled{"已开启"}else{"已关闭"}).text_color(MUTED))
        .child(Element::new(ElementType::Button,None).without_default_styles().width(64).height(34).radius(17)
            .bg(if enabled{"#638876"}else{"#4B505B"}).relative().on(Event::Click,"toggle_service")
            .child(thumb));
    root=root.child(power).child(text("请保持手环端应用前台运行（垂腕或覆盖息屏均不会导致退出前台）")
        .size(12).text_color(MUTED).relative().z_index(1));
    let columns=if width<680 {"minmax(0, 1fr)"}else{"repeat(3, minmax(0, 1fr))"};
    let mut lights=Element::new(ElementType::Grid,None).relative().z_index(1).width_full().grid_template_columns(columns).gap(12);
    for s in stages {
        let active=selected==Some(s.id.as_str());
        let color=match s.status.as_str(){"green"=>"#83B69B","red"=>"#D38A8A","guide"=>MUTED,_=>"#D2B47C"};
        let state=s.status_label.as_deref().unwrap_or(match s.status.as_str(){"green"=>"正常","red"=>"故障",_=>"待完成"});
        let card=Element::new(ElementType::Div,None).without_default_styles().padding(18).radius(20)
            .min_height(128).flex().flex_direction(FlexDirection::Column).gap(12)
            .bg(if active{"#394453"}else{BG}).border(1,if active{"#9BACBF"}else{"#454A55"})
            .on(Event::Click,&format!("stage:{}",s.id))
            .child(Element::new(ElementType::Div,None).flex().align_center().gap(8)
                .child(Element::new(ElementType::Div,None).width(10).height(10).radius(5).bg(color))
                .child(text(state).text_color(color)))
            .child(text(&s.title));
        lights=lights.child(card);
    }
    root=root.child(lights);
    let mut info=Element::new(ElementType::Div,None).relative().z_index(1).width_full()
        .min_height(340).padding(24).radius(20).bg(BG).border(1,"#454A55")
        .flex().flex_direction(FlexDirection::Column).gap(16);
    if let Some(s)=stages.iter().find(|s|Some(s.id.as_str())==selected) {
        info=info.child(Element::new(ElementType::Div,None).flex().align_center().gap(16)
            .child(text(&s.title).flex_grow(1.0)).child(button("返回总览","overview")));
        info=info.child(text(&s.message));
        if s.id=="device" {info=info.child(device_picker(devices,bound_addr)).child(text("初版1.3.1版针对小米手环11开发，固件4.100.139，其他设备正在努力适配中").text_color(MUTED));}
        let instructions=if s.solution.is_empty(){&s.steps}else{&s.solution};
        for (n,step) in instructions.iter().enumerate(){info=info.child(text(&format!("{}. {step}",n+1)).text_color(MUTED));}
        if s.id=="hooks" {
            info=info.child(text("需要现有 Python 3.10+，且包含 tkinter/_tkinter。缺失或版本不足会报错退出，请自行配置；本工具不会安装或升级 Python。").text_color(MUTED));
            info=info.child(text("命令会验证授权窗口，必要时解压本工具专用 Tcl/Tk 支持文件，备份并配置本项目五项钩子；已有 Tk 正常时直接复用。不修改系统 PATH、不自动信任钩子。随包 Tcl/Tk 的压缩包和解压占用合计约 7 MB。").text_color(MUTED).size(14));
            info=info.child(text("授权等待 60 秒后回到原生授权；下次请求仍使用手环和桌面窗口。").text_color(MUTED).size(14));
            let command=crate::hook_commands::script("Configure-Codex.ps1",false,epoch);
            info=info.child(text("安装命令（PowerShell）"))
                .child(Element::new(ElementType::Textarea,None).prop("value",&command).prop("readOnly","true")
                    .width_full().height(112).padding(10).radius(8).bg("#1C1F24").text_color(TEXT).border(1,"#454A55"))
                .child(button("复制安装命令","copy_install"));
        }
        let mut controls=Element::new(ElementType::Grid,None).grid_template_columns(if width<680{"minmax(0, 1fr)"}else{"repeat(3, minmax(0, 1fr))"}).gap(10);
        for action in &s.actions {if action!="devices" && !(s.id=="device" && action=="refresh") {controls=controls.child(button(label(action),action));}}
        info=info.child(controls);
        if let Some(code)=&s.code {
            info=info.child(button(if diagnostics{"收起诊断信息"}else{"查看诊断信息"},"toggle_diagnostics"));
            if diagnostics {
                info=info.child(text(&format!("诊断代码：{code}")).text_color(MUTED));
                if let Some(native)=&s.native_code {info=info.child(text(&format!("设备返回：{native}")).text_color(MUTED));}
            }
        }
        if !notice.is_empty(){info=info.child(text(notice).text_color("#D2B47C"));}
    }else {info=info.justify_center().align_center().child(text(if enabled{"连接正常，功能已开启"}else{"连接测试通过，请配置钩子后打开开关"}).text_color("#83B69B"));}
    ui::render(id,root.child(info));
}
