"""BitTune roadshow deck. Spoken Chinese, light layout, no invented scale."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

OUT = Path(__file__).with_name("比特音路演.pptx")

W = Inches(13.333)
H = Inches(7.5)
FONT = "Microsoft YaHei"

PAPER = RGBColor(0xF6, 0xF3, 0xEE)
INK = RGBColor(0x1C, 0x19, 0x17)
MUTED = RGBColor(0x5C, 0x56, 0x50)
FAINT = RGBColor(0x8A, 0x83, 0x7A)
RED = RGBColor(0x8E, 0x2F, 0x2A)
RULE = RGBColor(0xDD, 0xD6, 0xCC)
WASH = RGBColor(0xEB, 0xE4, 0xD8)

FORBIDDEN = (
    "已全球上架",
    "一键全球",
    "自动打款",
    "自动汇出",
    "已上链",
    "已认证",
    "情绪引擎已全量",
    "平台已代为登录",
    "日活跃",
    "GMV",
    "融资额",
    "估值",
    "闭环",
    "壁垒",
    "赋能",
    "抓手",
    "底层逻辑",
    "北极星",
)
REQUIRED = (
    "superformersmusic.com",
    "10%",
    "20%",
    "分发许可",
    "发现页上的发布，不是音乐平台上架",
    "歌曲页面",
    "Chrome",
)


def _font(run, size: int, color: RGBColor, bold: bool = False) -> None:
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        node = rpr.find(qn(tag))
        if node is None:
            node = etree.SubElement(rpr, qn(tag))
        node.set("typeface", FONT)


def add_shape(slide, kind, x, y, w, h, fill: RGBColor):
    shape = slide.shapes.add_shape(kind, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    return shape


def add_text(slide, x, y, w, h, text, size, color, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.auto_size = None
    frame.margin_left = Emu(0)
    frame.margin_right = Emu(0)
    frame.margin_top = Emu(0)
    frame.margin_bottom = Emu(0)
    try:
        frame._txBody.bodyPr.set(
            "anchor",
            {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor],
        )
    except Exception:
        pass
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(6)
        run = paragraph.add_run()
        run.text = line
        _font(run, size, color, bold)
    return box


def paint(slide) -> None:
    bg = add_shape(slide, MSO_SHAPE.RECTANGLE, 0, 0, W, H, PAPER)
    tree = slide.shapes._spTree
    element = bg._element
    tree.remove(element)
    tree.insert(2, element)


def blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    paint(slide)
    add_shape(slide, MSO_SHAPE.RECTANGLE, 0, 0, W, Inches(0.08), RED)
    return slide


def notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text.strip()


def footer(slide, page: int, total: int = 14) -> None:
    add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(6.95), Inches(11.9), Inches(0.01), RULE)
    add_text(slide, Inches(0.7), Inches(7.05), Inches(8), Inches(0.28), "比特音", 12, FAINT)
    add_text(slide, Inches(9.5), Inches(7.05), Inches(3.1), Inches(0.28), f"{page} / {total}", 12, FAINT, align=PP_ALIGN.RIGHT)


def heading(slide, text: str) -> None:
    add_text(slide, Inches(0.7), Inches(0.38), Inches(12), Inches(1.15), text, 32, INK, True)


def slide_cover(prs):
    slide = blank(prs)
    add_text(slide, Inches(0.7), Inches(1.45), Inches(11), Inches(0.9), "比特音", 60, INK, True)
    add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(0.72), Inches(2.5), Inches(1.4), Inches(0.045), RED)
    add_text(
        slide,
        Inches(0.7),
        Inches(2.85),
        Inches(10.5),
        Inches(1.6),
        "独立音乐人把歌发到音乐平台，\n再把平台里的收入对回这首歌。",
        28,
        INK,
    )
    add_text(
        slide,
        Inches(0.7),
        Inches(4.85),
        Inches(10),
        Inches(0.8),
        "做歌用额度。平台上的钱另记一本账。\n没有这首歌的页面，就不算上架。",
        18,
        MUTED,
    )
    add_text(slide, Inches(0.7), Inches(6.35), Inches(8), Inches(0.35), "superformersmusic.com", 16, RED, True)
    notes(
        slide,
        """
先说产品是干什么的，不要先说愿景口号。
如果要对照：汽水帮音乐人把歌送进抖音。我们做的是歌发出去之后，各音乐平台后台里的钱能不能对上这首歌。
不要说已经发到所有平台，也不要说钱会自己到银行卡。
""",
    )


def slide_problem(prs):
    slide = blank(prs)
    heading(slide, "做歌已经不难，钱还在各家后台里")
    add_text(
        slide,
        Inches(0.7),
        Inches(1.85),
        Inches(11.6),
        Inches(1.3),
        "写一首歌，现在已经有不少工具。\n歌上了网易云、QQ 音乐、汽水音乐之后，钱还在各家后台里，经常对不上是哪一首。",
        20,
        INK,
    )
    lines = [
        ("播放看得到", "没有金额的播放，只能看，不能当收入。"),
        ("对不上歌", "对不上具体作品的账单，不进创作者的钱包。"),
        ("两本账分开", "做歌扣额度。平台的钱来自账单，不能混成一笔。"),
    ]
    for index, (name, body) in enumerate(lines):
        y = 3.55 + index * 1.0
        add_text(slide, Inches(0.7), Inches(y), Inches(2.6), Inches(0.7), name, 18, RED, True, anchor=MSO_ANCHOR.MIDDLE)
        add_text(slide, Inches(3.5), Inches(y), Inches(8.8), Inches(0.7), body, 18, INK, anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, 2)
    notes(
        slide,
        """
这页讲结构，不讲用户规模。我们没有准备用户数或收入数字。
电台里的完播、发现页上的热度，都不是可提现余额。
""",
    )


def slide_product(prs):
    slide = blank(prs)
    heading(slide, "产品做这三件事")
    blocks = [
        ("做歌", "用一句话，或选一个风格，生成一首歌。额度不够就不能生成。"),
        ("交到平台", "在创作者自己已经登录的浏览器里填表。现在默认只勾网易云。Spotify 没配对时只同步数据，不会自动勾上。短视频先交给运营，不显示成已经上架。"),
        ("把账单对上", "从后台抄回带金额的记录，对到这首歌。抄到的钱先是草稿，确认之后才能提。"),
    ]
    for index, (name, body) in enumerate(blocks):
        y = 1.85 + index * 1.55
        add_text(slide, Inches(0.7), Inches(y), Inches(2.3), Inches(1.2), name, 22, RED, True)
        add_text(slide, Inches(3.2), Inches(y), Inches(9.2), Inches(1.3), body, 18, INK)
    footer(slide, 3)
    notes(
        slide,
        """
三件事对应后面的页面，不要再拆一套新名词。
短视频不是故障，是还没有自动上架，所以进运营处理。
""",
    )


def slide_who(prs):
    slide = blank(prs)
    heading(slide, "给自己做歌、自己发歌的人")
    add_text(
        slide,
        Inches(0.7),
        Inches(1.75),
        Inches(11.8),
        Inches(1.15),
        "他们要的不是再多一个播放器。\n他们要知道：这首歌交到了哪家平台，那家后台里有没有这笔钱。",
        20,
        INK,
    )
    add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(3.2), Inches(5.7), Inches(3.2), WASH)
    add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(6.7), Inches(3.2), Inches(5.9), Inches(3.2), WASH)
    add_text(slide, Inches(0.95), Inches(3.4), Inches(5.2), Inches(0.45), "手机小程序", 20, INK, True)
    add_text(slide, Inches(0.95), Inches(4.05), Inches(5.2), Inches(1.9), "听歌、做歌、签到、看收入。\n不能在小程序里填各平台的表，\n也不能做电脑上的波形修改。", 16, MUTED)
    add_text(slide, Inches(6.95), Inches(3.4), Inches(5.4), Inches(0.45), "电脑浏览器", 20, INK, True)
    add_text(slide, Inches(6.95), Inches(4.05), Inches(5.4), Inches(1.9), "安装 Chrome 扩展。\n在自己已经登录的音乐人后台里填表、抄账单。\n需要修歌时，在电脑上改波形，改完仍是一首立体声。", 16, MUTED)
    footer(slide, 4)
    notes(
        slide,
        """
小程序如果要继续填表，是复制创作者台的链接，到电脑上打开。不要说微信里就能代填后台。
修歌打出来的是一首新的立体声。发行用这首，不用被换掉的原曲。
""",
    )


def slide_path(prs):
    slide = blank(prs)
    heading(slide, "一首歌实际怎么走")
    steps = [
        "做歌，扣除创作额度。",
        "可以先修一版。修完是一首新歌，发行用新的这首。",
        "质检通过后再提交。",
        "进度集中在一张卡上：要验证码、表填了一半、等你登录，或已经有歌曲页面。",
        "音乐平台上出现这首歌的页面，才算上架。",
        "签过分发许可，才会把账单金额结算进来。",
        "账单先是草稿。运营确认后才能申请提现，钱由财务打出。",
    ]
    for index, line in enumerate(steps):
        y = 1.7 + index * 0.68
        add_text(slide, Inches(0.7), Inches(y), Inches(0.45), Inches(0.45), str(index + 1), 16, RED, True)
        add_text(slide, Inches(1.3), Inches(y), Inches(11.2), Inches(0.55), line, 16, INK)
    footer(slide, 5)
    notes(
        slide,
        """
界面上这张进度卡叫完成带。讲解时指着屏幕说「就看这张卡停在哪」，不必先解释内部名字。
没有歌曲页面的状态，不要叫上架。周五的任务不会把钱打到银行卡。
""",
    )


def slide_today(prs):
    slide = blank(prs)
    heading(slide, "网站现在能打开，能看这四块")
    add_text(slide, Inches(0.7), Inches(1.65), Inches(11), Inches(0.4), "superformersmusic.com", 20, RED, True)
    items = [
        ("做歌和曲库", "能生成，也能把已有的歌点开听。"),
        ("发现", "可以发布、搜索、参加挑战。\n发现页上的发布，不是音乐平台上架。"),
        ("发行进度", "看这一单卡在哪：要验证码、表填了一半、等登录，\n或已经有歌曲页面。"),
        ("收入", "草稿和可提现分开。确认前不能提现。"),
    ]
    for index, (name, body) in enumerate(items):
        col = index % 2
        row = index // 2
        x = 0.7 + col * 6.2
        y = 2.35 + row * 2.0
        add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.08), Inches(1.55), RED)
        add_text(slide, Inches(x + 0.3), Inches(y), Inches(5.5), Inches(0.45), name, 20, INK, True)
        add_text(slide, Inches(x + 0.3), Inches(y + 0.55), Inches(5.5), Inches(0.9), body, 16, MUTED)
    footer(slide, 6)
    notes(
        slide,
        """
发布后查过：首页和 /api/v1/health 都是 200，数据库和 Redis 正常。
情绪分析的模型文件还没放到服务器上。被问到就说这项还不准，不要改口说已经能稳定判断情绪。
""",
    )


def slide_rules(prs):
    slide = blank(prs)
    heading(slide, "三条不能让步的规则")
    rules = [
        ("没有歌曲页面，不能标上架。", "上传入口的网址不算。必须是这首歌在平台上的页面。"),
        ("没有分发许可，不能把钱结算进钱包。", "用户要先签许可。没签，就停在这里，不编一笔可提现。"),
        ("草稿不能自己点成可提现。", "对账很有把握的小额，系统可以先收下。其余等运营确认。"),
    ]
    for index, (name, body) in enumerate(rules):
        y = 1.85 + index * 1.55
        add_text(slide, Inches(0.7), Inches(y), Inches(12), Inches(0.5), name, 24, INK, True)
        add_text(slide, Inches(0.7), Inches(y + 0.55), Inches(12), Inches(0.55), body, 18, MUTED)
    footer(slide, 7)
    notes(
        slide,
        """
这三句建议放慢读。投资人如果只记住一页，记住这页。
高置信小额先收下，仍然不是已经打到银行卡。
""",
    )


def slide_system(prs):
    slide = blank(prs)
    heading(slide, "系统分成这几块")
    rows = [
        ("网页和小程序", "同一套界面。小程序不负责填各平台的表。"),
        ("服务和队列", "接口用 FastAPI。生成、投递、抄账放在后台排队，页面不用干等。"),
        ("Chrome 扩展", "只操作创作者自己打开、并已经登录的页面。用来填表，也用来抄当前账单。"),
        ("权限分开", "可以填表、可以结算、或只能看数据，是分开授权的。没开结算，就不会去结钱。"),
        ("存储", "歌、账和文件分别在 PostgreSQL、Redis 和对象存储里。"),
    ]
    for index, (name, body) in enumerate(rows):
        y = 1.7 + index * 0.95
        add_text(slide, Inches(0.7), Inches(y), Inches(3.1), Inches(0.7), name, 18, RED, True, anchor=MSO_ANCHOR.MIDDLE)
        add_text(slide, Inches(4.0), Inches(y), Inches(8.5), Inches(0.75), body, 16, INK, anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, 8)
    notes(
        slide,
        """
自动打开各平台后台的农场导航目前是关的。抄账靠创作者自己浏览器里的扩展。
不要说平台替用户登录了各家后台。生产环境要跑齐接口、worker 和定时任务，缺了投递 worker，后面的自动步骤是空的。这句等被问到再讲。
""",
    )


def slide_auto(prs):
    slide = blank(prs)
    heading(slide, "哪些步骤会自己继续，哪些必须停")
    add_text(slide, Inches(0.7), Inches(1.7), Inches(5.6), Inches(0.4), "会继续", 18, RED, True)
    add_text(slide, Inches(6.9), Inches(1.7), Inches(5.6), Inches(0.4), "会停住", 18, INK, True)
    left = [
        "回到创作者台，上次还没确认的发行会再问一次。",
        "平台在等登录，扩展也在线，就打开那家平台一次。",
        "表填到一半，扩展在线就继续填，不用重新确认。",
        "有了歌曲页面，并且签了许可，就排队去抄账。",
    ]
    right = [
        "没签分发许可，不去结算。",
        "没有歌曲页面，不算上架。",
        "已经有草稿，就打开草稿，不再抄一次。",
        "提现之后等财务回单。周五不会把钱打出。",
    ]
    for index, line in enumerate(left):
        y = 2.3 + index * 1.05
        add_text(slide, Inches(0.7), Inches(y), Inches(5.7), Inches(0.95), line, 16, INK)
    for index, line in enumerate(right):
        y = 2.3 + index * 1.05
        add_text(slide, Inches(6.9), Inches(y), Inches(5.7), Inches(0.95), line, 16, INK)
    footer(slide, 9)
    notes(
        slide,
        """
继续填、打开平台、排队抄账，都是一次，不是无限重试，也不是悄悄重新提交。
页面上还有「重试填表」。那是创作者自己再交一次。抄到的金额要等回传，不要说已经到账。
""",
    )


def slide_money(prs):
    slide = blank(prs)
    heading(slide, "钱从哪来")
    add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.75), Inches(12), Inches(1.7), WASH)
    add_text(slide, Inches(0.95), Inches(1.95), Inches(5.2), Inches(0.35), "自己发", 14, MUTED)
    add_text(slide, Inches(0.95), Inches(2.3), Inches(5.2), Inches(0.7), "10%", 36, RED, True)
    add_text(slide, Inches(6.7), Inches(1.95), Inches(5.5), Inches(0.35), "走厂牌，默认", 14, MUTED)
    add_text(slide, Inches(6.7), Inches(2.3), Inches(5.5), Inches(0.7), "20%", 36, INK, True)
    rows = [
        ("创作额度", "注册会送，签到可以补，做歌之前扣。这不是版税。"),
        ("效果包", "按已经发出去的歌计算，不按修了几次计算。"),
        ("短视频和游戏授权", "平台还没进账时可以单卖。这不是平台版税已经到账。"),
        ("合同范围", "分成可以写在 10% 到 30%。以签下的分发许可为准。"),
    ]
    for index, (name, body) in enumerate(rows):
        y = 3.7 + index * 0.72
        add_text(slide, Inches(0.7), Inches(y), Inches(3.2), Inches(0.55), name, 16, INK, True)
        add_text(slide, Inches(4.0), Inches(y), Inches(8.5), Inches(0.55), body, 16, MUTED)
    footer(slide, 10)
    notes(
        slide,
        """
给企业拆多套系统、对外开放接口，还没当成现在的收入。被问到就说有骨架，不是这页的数。
不要报交易规模、日活或融资金额。
""",
    )


def slide_diff(prs):
    slide = blank(prs)
    heading(slide, "和只负责生成歌曲的产品差在后两步")
    add_text(
        slide,
        Inches(0.7),
        Inches(1.75),
        Inches(11.8),
        Inches(1.0),
        "生成到文件，很多产品都能做。后面还要有平台上的歌曲页面，以及能对回这首歌的账单。",
        20,
        INK,
    )
    points = [
        "版权不锁三年，歌还是创作者的。",
        "不保存平台密码，也不去解验证码。只在创作者自己登录并授权之后抄账单。",
        "对不上这首歌的账单行，不进钱包。",
        "内部状态、上传入口的链接，都不能代替歌曲页面。",
    ]
    for index, line in enumerate(points):
        y = 3.15 + index * 0.85
        add_shape(slide, MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(y + 0.12), Inches(0.12), Inches(0.12), RED)
        add_text(slide, Inches(1.1), Inches(y), Inches(11.3), Inches(0.7), line, 18, INK)
    footer(slide, 11)
    notes(
        slide,
        """
不要讲成我们有独家音乐模型。生成用的是已经接入的模型，自己训练大模型不是现在要做的事。
差别成立的前提，是创作者自己有平台账号，并且愿意授权。
""",
    )


def slide_not_yet(prs):
    slide = blank(prs)
    heading(slide, "这些还不能说已经做好")
    items = [
        ("代发到海外店", "DistroKid、TuneCore 没有密钥时，先交给运营处理。"),
        ("实名", "提现前人工看。没有接第三方核验。"),
        ("自动打开后台", "这项关着。抄账靠创作者自己的 Chrome 扩展。"),
        ("微信里付款", "小程序能看额度和价格。虚拟支付还没接。"),
        ("分轨证明和链上记录", "还在方案里，不是现在能演示的结果。"),
        ("情绪分析", "模型文件还没放到服务器上，这项先不要讲成已经准确。"),
    ]
    for index, (name, body) in enumerate(items):
        col = index % 2
        row = index // 2
        x = 0.7 + col * 6.25
        y = 1.8 + row * 1.55
        add_text(slide, Inches(x), Inches(y), Inches(5.8), Inches(0.4), name, 18, RED, True)
        add_text(slide, Inches(x), Inches(y + 0.45), Inches(5.8), Inches(0.85), body, 15, INK)
    footer(slide, 12)
    notes(
        slide,
        """
这页主动翻。主动说还没做的，比被问住再改口好。
嵌入播放器、连续包月、多套租户，同样不要说成已经在卖。
""",
    )


def slide_next(prs):
    slide = blank(prs)
    heading(slide, "下一步只做三件具体的事")
    steps = [
        ("先走通网易云", "填表、拿到歌曲页面、形成账单草稿。扩展在线时，少让人重复点。"),
        ("有密钥再代发", "平台正式接口或合作方密钥到了，才打开代发，以及自动打开后台。在那之前，运营队列和扩展就是现在的做法。"),
        ("补上情绪分析的文件", "模型文件放到服务器之后，情绪分析才谈得上可用。"),
    ]
    for index, (name, body) in enumerate(steps):
        y = 1.85 + index * 1.55
        add_text(slide, Inches(0.7), Inches(y), Inches(12), Inches(0.45), name, 22, INK, True)
        add_text(slide, Inches(0.7), Inches(y + 0.55), Inches(12), Inches(0.7), body, 18, MUTED)
    footer(slide, 13)
    notes(
        slide,
        """
不要承诺上线日期，也不要承诺能覆盖多少家店。
如果对方要合作，需要的是平台正式接口，或创作者登录后的授权，不是再看一次生成演示。
""",
    )


def slide_demo(prs):
    slide = blank(prs)
    heading(slide, "现场就看三处")
    add_text(
        slide,
        Inches(0.7),
        Inches(1.7),
        Inches(12),
        Inches(1.5),
        "打开 superformersmusic.com。\n做一首，或从曲库点开一首，确认听得见。\n打开发行进度，看这一单停在哪。再打开收入。",
        20,
        INK,
    )
    add_text(slide, Inches(0.7), Inches(3.5), Inches(12), Inches(0.4), "有草稿，就说确认前不能提现。没有金额，就讲规则，不要现编一笔钱。", 18, RED, True)
    add_text(slide, Inches(0.7), Inches(4.2), Inches(12), Inches(0.4), "这几句不要说", 18, INK, True)
    dont = "\n".join(
        [
            "不要说已经发到所有平台。",
            "不要说周五会把钱打出。",
            "不要把发现页上的发布说成音乐平台上架。",
            "不要说我们替用户登录了各平台。",
            "不要报材料里没有的用户数或收入。",
        ]
    )
    add_text(slide, Inches(0.7), Inches(4.7), Inches(12), Inches(1.9), dont, 16, MUTED)
    footer(slide, 14)
    notes(
        slide,
        """
演示前自己先打开首页。如果健康检查里模型文件仍然没有，被问到情绪分析就按「还没放上服务器」说。
收入页是空的也可以。空的时候讲规则，比临时造一笔收入可信。
""",
    )


def collect_text(prs: Presentation) -> str:
    chunks: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                chunks.append(shape.text_frame.text)
        if slide.has_notes_slide:
            chunks.append(slide.notes_slide.notes_text_frame.text)
    return "\n".join(chunks)


def honesty_check(path: Path) -> None:
    prs = Presentation(str(path))
    if len(prs.slides) != 14:
        raise SystemExit(f"expected 14 slides, got {len(prs.slides)}")
    for index, slide in enumerate(prs.slides, start=1):
        if not slide.has_notes_slide or not slide.notes_slide.notes_text_frame.text.strip():
            raise SystemExit(f"slide {index} missing speaker notes")
    text = collect_text(prs)
    for phrase in FORBIDDEN:
        if phrase in text:
            raise SystemExit(f"forbidden phrase present: {phrase}")
    for phrase in REQUIRED:
        if phrase not in text:
            raise SystemExit(f"required phrase missing: {phrase}")


def main() -> None:
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    prs.core_properties.title = "比特音路演"
    prs.core_properties.subject = "独立音乐人把歌发到音乐平台，再把收入对回这首歌"
    prs.core_properties.author = "BitTune"
    for builder in (
        slide_cover,
        slide_problem,
        slide_product,
        slide_who,
        slide_path,
        slide_today,
        slide_rules,
        slide_system,
        slide_auto,
        slide_money,
        slide_diff,
        slide_not_yet,
        slide_next,
        slide_demo,
    ):
        builder(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    honesty_check(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
