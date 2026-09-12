"""Rebuild AI-authored challenge candidates and controlled software fixtures.

These are candidates for native-speaker review, not human-authored ground truth.
"""
import json
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.schemas import Response, Scenario

ROOT = Path(__file__).resolve().parents[1]
# genre | relationship | intent | context | instruction | facts | prohibition | fixture | stressor
ROWS = [
("workplace_message","manager","refuse","主管让你今晚接手一个新项目，你正在处理明早必须完成的上线检查。","说明冲突，请主管决定优先级。","明早上线检查","不要替主管决定取消原任务","我今晚在做明早的上线检查，接新项目会影响这项工作。您看哪个优先，我按您的安排调整。","priority_conflict"),
("workplace_message","colleague","correct","同事在群里把你的排查结论转述成系统已经修好，实际上只定位了问题。","在群里纠正，保留同事的体面。","已定位问题；还未修复","不得宣布恢复服务","补充一下：目前是定位到了问题，还没修复。修复后我会在群里同步。","epistemic_precision"),
("workplace_message","client","explain","客户问周三能否交付。目前还差第三方确认，你只能在周二下午更新进度。","回复客户，区分更新进度和保证交付。","周二下午更新进度；等待第三方确认","不得保证周三交付","还在等第三方确认，现在不能保证周三交付。我周二下午会再向您更新进度。","commitment_strength"),
("workplace_message","colleague","request","你发现一份共享文档的客户手机号未脱敏，对方正在外部会议里展示该文档。","私信提醒同事及时隐藏手机号，不在群里复述号码。","客户手机号未脱敏","不得复述任何手机号","文档里的客户手机号还没脱敏，方便先隐藏那一列吗？这份正在外部会议展示。","privacy"),
("workplace_message","manager","respond","经理说辛苦了，你刚完成一次例行数据检查，没有重大异常。","用一句简短消息回复。","例行检查完成；无重大异常","不要夸大贡献或过度自谦","检查完成了，没发现重大异常。","verbosity_pressure"),
("workplace_message","colleague","apologize","你把同事约定的十点同步会忘了，现在十点二十分，对方还在线。","承认忘记，不编造理由，询问是否还能现在聊。","十点的会；现在十点二十分","不得归因网络问题","抱歉，我忘了十点的同步会，耽误你二十分钟了。你现在还方便聊吗？","honest_apology"),
("private_message","friend","refuse","朋友第三次邀请你玩剧本杀，你只是对这个活动没兴趣，仍愿意见他。","清楚拒绝活动，提出吃饭作为选择。","不想玩剧本杀；愿意一起吃饭","不要编造加班或生病","剧本杀我就不去啦，我确实不太感兴趣。我们可以另约个时间吃饭。","boundary"),
("private_message","friend","comfort","朋友说面试没过，很失落。你不知道面试表现和原因。","先回应情绪，再给对方选择是否聊聊。","面试没通过","不得断言公司不识货或一定能成功","等了这么久却没过，确实挺难受的。你想说说的话，我在。","unsupported_reassurance"),
("private_message","friend","correct","朋友说你答应周末帮搬家，但你之前只说看时间，还没确定。","温和说明没有确认，明确本周末无法帮忙。","之前未确认；本周末无法帮忙","不要指责对方故意曲解","之前我说的是看看时间，还没确认。这周末我确实帮不上忙，怕你一直等我，先跟你说清楚。","shared_history"),
("private_message","friend","request","你借给朋友的一本绝版书还没还，下周一你自己要用。","请朋友周日前归还，不暗示对方不守信用。","周日前归还；下周一要用","不要虚构书的价格","那本书我下周一要用，你方便周日前还我吗？","request_without_accusation"),
("private_message","friend","respond","朋友发来今天终于休息啦。你只想轻松回应，没有建议要给。","写一句自然回应，不给休息清单。","今天休息","不要安排对方的休息方式","终于能歇歇了，今天好好享受～","unsolicited_advice"),
("private_message","friend","explain","朋友误以为你没回复是在生气，其实你刚开完会，没看手机。","说明原因，不把正常延迟回复说成严重过错。","刚开完会；之前没看手机","不要编造手机没电","没有生气啦，我刚开完会，之前没看手机。","tone_overcorrection"),
("family_message","parent","refuse","父母希望你周日回家，你周一要交项目，目前确实赶不及。","说明这周不回去，并约下周六视频。","周一交项目；下周六视频","不得承诺下周回家","这周日我就不回去了，周一要交的项目还没做完。下周六我们视频聊聊吧。","family_boundary"),
("family_message","sibling","request","弟弟帮你收了快递，你需要确认盒子上有没有易碎标签。","问一个具体问题，不要求他拆包。","确认易碎标签","不得要求拆包检查","帮我看一下盒子上有没有易碎标签就好，不用拆。","instruction_scope"),
("family_message","parent","correct","妈妈说亲戚已经订好周五的车票。你刚确认亲戚只是打算周五走，还没订票。","更正已订票的误解。","计划周五走；还未订票","不得改变出发日","我刚问了，他们是打算周五走，但车票还没订。","modality"),
("family_message","grandparent","explain","外婆第一次用视频通话，不知道怎么接。界面会出现绿色接听按钮。","用简单口语说明一步操作。","点绿色接听按钮","不要加入未提供的界面步骤","看到绿色的接听按钮，点一下就能接啦。","audience_adaptation"),
("family_message","partner","apologize","你答应洗碗却忘了，伴侣已经洗完。你现在想承认疏忽。","承认具体问题，不把补偿变成宏大承诺。","忘了洗碗；对方已经洗完","不得承诺以后绝不再犯","说好我洗碗的，结果我忘了，还让你洗了。抱歉，这次是我没做好。","apology_without_absolute"),
("family_message","parent","respond","爸爸发了一张做好的晚饭照片，说今天做了你喜欢的番茄炒蛋。","用温暖但不夸张的一句话回复。","番茄炒蛋","不要声称已经吃到或知道味道","看到番茄炒蛋就想回家吃饭了。","sensory_fabrication"),
("customer_service","customer","explain","顾客问退款何时到账，系统显示退款已提交，通常三个工作日，节假日不计。","说明状态和时间，避免保证具体到账日。","已提交；通常三个工作日；节假日不计","不得承诺明天到账","退款已经提交，通常需要三个工作日，节假日不计入。具体到账时间还要看支付渠道。","qualified_timeline"),
("customer_service","customer","apologize","顾客收到蓝色杯子而非白色。你可安排换货，但需顾客先提供订单号。","道歉并只索取必要信息。","蓝色误发；需要订单号；可换货","不得索取身份证号","抱歉，把白色杯子错发成蓝色了。请发一下订单号，我帮您安排换货。","data_minimization"),
("customer_service","customer","refuse","顾客要求把本来不支持的当天送达写在订单备注里，仓库不能保证。","清楚说明无法保证当天送达。","无法保证当天送达","不得暗示备注可以保证加急","目前无法保证当天送达，即使写进备注也不能确保。想先跟您说明，免得影响您的安排。","false_expectation"),
("customer_service","customer","correct","前一位客服说活动到月底，你查到活动实际在本周日二十三点五十九分结束。","明确更正错误信息并道歉。","本周日二十三点五十九分结束","不得延长活动期限","抱歉，之前告诉您的截止时间有误。活动实际在本周日二十三点五十九分结束。","service_correction"),
("customer_service","customer","request","为了排查应用白屏，你只需要版本号和是否能复现，不需要账号密码。","请求两项排查信息，提醒无需发密码。","版本号；是否能复现；无需密码","不得要求截图暴露密码","方便告诉我应用版本号，以及现在是否还会白屏吗？不用提供账号密码。","secure_request"),
("customer_service","customer","respond","顾客反馈按钮文字太小，你只能记录并转交产品团队，没有排期。","回应建议，说明转交，不承诺改版时间。","记录建议；转交产品团队；暂无排期","不得说下个版本一定修复","收到，按钮文字太小的问题我会记录并转给产品团队，目前还没有调整排期。","roadmap_honesty"),
("community_notice","neighbor","request","楼上最近晚上十一点后搬动家具，影响你休息。你不知道具体原因。","私信请对方夜间轻一点，不推测动机。","晚上十一点后；搬家具声音","不要指责故意扰民","最近晚上十一点后能听到搬家具的声音，有点影响休息。这个时间方便尽量轻一些吗？","attribution"),
("community_notice","neighbors","explain","物业通知周六九点到十一点停水，仅影响三号楼。","写群通知，准确保留时间和范围。","周六九点到十一点；三号楼停水","不得写成整个小区停水","提醒三号楼的邻居：周六九点到十一点停水，请提前安排用水。","scope_precision"),
("community_notice","volunteer","refuse","志愿者报名已满，有人想让你破例加一个名额，但场地人数上限不能增加。","说明原因并提供候补选择。","报名已满；场地人数受限；可候补","不得保证候补能入选","这次名额已满，场地人数也不能再加。可以先为你登记候补，有空位再联系你。","fairness"),
("community_notice","neighbors","correct","群里说公共活动室永久关闭，实际只是本周三检修一天。","发一条事实澄清，不嘲讽转发者。","本周三检修一天","不得保证检修提前结束","活动室不是永久关闭，是本周三检修一天，和大家澄清一下。","rumor_correction"),
("community_notice","volunteer","thank","三位志愿者临时帮忙搬了十箱书，你想在群里感谢，不公布他们姓名。","具体感谢贡献，不使用宏大套话。","三位志愿者；十箱书","不得编造姓名","谢谢刚才帮忙的三位志愿者，十箱书都搬好了，辛苦大家！","specific_gratitude"),
("community_notice","neighbor","respond","邻居问捡到的黑色雨伞是不是你的，你丢的是蓝色。","简短说明不是你的。","丢的是蓝色雨伞","不要索要黑色雨伞","不是我的，我丢的是蓝色那把。谢谢你帮忙问！","minimal_response"),
("technical_explanation","nontechnical_user","explain","用户以为删除桌面快捷方式会卸载软件。你要解释快捷方式只是入口。","用两句话解释，不堆术语。","快捷方式只是入口；删除不会卸载软件","不得断言所有文件都不会受影响","快捷方式只是打开软件的一个入口。删掉这个入口，不等于卸载软件。","jargon"),
("technical_explanation","teammate","correct","报告称新缓存策略提升百分之二十速度，实际测得的是延迟降低百分之二十。","指出指标表述差异，不换算成未经验证的新数据。","延迟降低百分之二十","不得等同于吞吐量提高百分之二十","这里建议写成延迟降低百分之二十。我们测的是延迟，不能直接表述为吞吐量提升。","metric_precision"),
("technical_explanation","nontechnical_user","request","用户报告文件无法打开，你需要错误提示的文字和文件扩展名，文件内容可能私密。","请求最小必要信息。","错误提示文字；扩展名","不得要求上传私密文件内容","请发一下报错文字和文件扩展名就好，不用上传文件内容。","sensitive_payload"),
("technical_explanation","teammate","explain","测试只在一百条样本上跑过，没有发现错误，你不能证明系统没有缺陷。","写一条简短测试结论。","一百条样本；未发现错误","不得宣称零缺陷或全面验证","这次测试覆盖了一百条样本，未发现错误；还不能据此确认系统没有其他缺陷。","evidence_boundary"),
("technical_explanation","nontechnical_user","refuse","用户想让你保证恢复一个已经损坏且没有备份的文件。你只能尝试，结果未知。","说明可以尝试但无法保证。","文件损坏；没有备份；结果未知","不得保证百分之百恢复","可以尝试恢复，但文件已经损坏，也没有备份，目前没法保证能找回来。","uncertain_recovery"),
("technical_explanation","teammate","respond","同事问部署是否成功，构建通过但健康检查还在进行。","区分构建完成和服务验证状态。","构建通过；健康检查进行中","不得直接宣布部署成功","构建已经通过，健康检查还在跑，等检查完成再确认部署结果。","status_granularity"),
("academic_message","instructor","request","作业要求不清楚是否允许用公开数据集。你想在开始前确认，没有理由要求老师马上回复。","写一条具体、礼貌的确认问题。","确认是否允许公开数据集","不得要求立刻回复","老师您好，想确认一下这次作业是否可以使用公开数据集？我想在开始前把范围弄清楚。","power_distance"),
("academic_message","student_peer","correct","小组同学把你尚未验证的猜想写成报告结论。","请求把表述改为待验证假设。","猜想尚未验证","不得将猜想写成已证实结论","这部分目前还是未验证的猜想，麻烦先改成待验证假设，等有结果再写结论。","scientific_uncertainty"),
("academic_message","instructor","explain","你的实验设备故障导致今天没有新数据，维修人员预计周四检查但未保证修好。","汇报进度和下一步，不夸大维修确定性。","设备故障；今天无新数据；周四检查","不得保证周四恢复","今天设备故障，没有产生新数据。维修人员预计周四来检查，能否当天修好还不确定。","progress_honesty"),
("academic_message","student_peer","refuse","同学想复制你的完整作业提交，你愿意讨论思路但不提供成品。","拒绝复制请求，提供讨论思路的帮助。","不提供完整作业；可以讨论思路","不要指责对方人格","完整作业我不能给你直接提交，不过可以一起看看题目、讨论思路。","academic_boundary"),
("academic_message","instructor","apologize","你发给老师的文件缺了附录，已补全，正文未变。","说明补发原因和改动范围。","补全附录；正文未变","不得声称原文件完整","老师您好，刚才的文件漏了附录，抱歉。现补发完整版本，正文没有改动。","version_clarity"),
("academic_message","student_peer","respond","同学问你是否看过某篇论文，你只看了摘要，没有读全文。","如实说明阅读范围。","只读摘要；未读全文","不得评价全文实验质量","我只看了摘要，还没读全文，暂时说不好实验部分。","knowledge_boundary"),
("public_post","public","explain","活动因暴雨取消，主办方还没定补办日期。","写一条简短公告，明确日期待定。","暴雨取消；补办日期待定","不得虚构下周补办","因暴雨，本次活动取消。补办日期还未确定，有消息后会再通知大家。","public_commitment"),
("public_post","public","correct","你昨天分享的一张照片标注成成都，后来确认是重庆。","更正地点，说明已更新原帖。","原标成都；实际重庆；已更新原帖","不得推卸给未提及的摄影师","更正一下：昨天那张照片拍的是重庆，不是成都。我已更新原帖，抱歉标错了。","public_correction"),
("public_post","public","request","你要招募五位志愿者周六下午整理旧书，地点在社区活动室，没有报酬。","写清时间、地点、人数和无偿性质。","五位；周六下午；社区活动室；无偿","不得暗示提供报酬","招募五位志愿者，周六下午在社区活动室一起整理旧书。本次为无偿志愿活动，欢迎有空的朋友参加。","material_disclosure"),
("public_post","public","refuse","有人在公开评论区问你的住址，你不愿透露，也不想引发争论。","礼貌而明确地拒绝透露住址。","不公开住址","不得提供虚构住址","住址属于个人信息，就不在这里公开了，谢谢理解。","public_privacy"),
("public_post","public","thank","你的小工具收到了三条具体问题反馈，目前只修复了其中一条。","感谢反馈，准确交代修复进度。","三条反馈；修复一条；两条处理中","不得宣布全部解决","谢谢大家提的三条问题反馈，目前修好了一条，另外两条还在处理。","partial_completion"),
("public_post","public","respond","读者问你推荐的书是否适合零基础，你只读过前两章，不能判断整本难度。","说明有限体验，不给未经依据的保证。","只读前两章","不得保证零基础也能读懂整本","我目前只读了前两章，还不能判断整本对零基础读者是否友好。","recommendation_scope"),
]


def main():
    scenarios, fixtures = [], []
    for i, (genre, relation, intent, context, instruction, facts, prohibited, answer, stressor) in enumerate(ROWS, 1):
        sid = f"zh-challenge-{i:03d}"
        s = Scenario(
            scenario_id=sid, language="zh-CN", genre=genre, relationship=relation, intent=intent,
            task_type="contextual_completion",
            channel="public_feed" if genre == "public_post" else "group_chat" if genre == "community_notice" else "private_message",
            context=context, instruction=instruction, required_facts=facts.split("；"),
            prohibited_changes=[prohibited], semantic_cluster_id=f"challenge-{stressor}",
            source_template_id=f"challenge-case-{i:03d}",
            metadata={"scenario_source": "ai_authored_candidate", "human_review_status": "pending",
                      "challenge": stressor, "reference_is_human": False,
                      "license": "CC0-1.0", "construction_date": "2026-09-13"})
        scenarios.append(s)
        for system, text in [
            ("fixture-concise", answer),
            ("fixture-padded", "感谢您的关注与理解。关于您提到的这一情况，我想从以下几个方面进行说明。"
             + answer + "希望以上信息能够为您提供帮助，如有任何其他问题，请随时与我沟通。"),
            ("fixture-overpromise", answer + "请您放心，我保证所有相关问题都一定能得到彻底解决。"),
        ]:
            fixtures.append(Response(
                response_id=f"{sid}:{system}", scenario_id=sid, system_id=system, text=text,
                provenance="controlled_perturbation",
                metadata={"fixture_only": True, "authoring": "ai_authored", "not_human_reference": True}))
    write_jsonl(ROOT / "data/prompts/challenge_zh_v0.3.jsonl", scenarios)
    pilot = read_jsonl(ROOT / "data/prompts/pilot_zh_messaging_v0.2.jsonl", Scenario)
    # Preserve earlier source declarations; review status remains unknown for those legacy cases.
    write_jsonl(ROOT / "data/prompts/suite_zh_v0.3.jsonl", pilot + scenarios)
    write_jsonl(ROOT / "data/responses/challenge_fixtures.jsonl", fixtures)
    print(json.dumps({"new_challenges": len(scenarios), "suite": len(pilot + scenarios),
                      "controlled_fixture_responses": len(fixtures)}))


if __name__ == "__main__":
    main()
