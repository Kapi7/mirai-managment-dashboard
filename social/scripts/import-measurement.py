"""Build an aggregate-only social report from Mirai measurement artifacts.
No credentials, customer orders, comment text, or local paths are copied.
Usage: python3 social/scripts/import-measurement.py ARTIFACT_DIR LOCAL_AUDIT_DIR OUTPUT
"""
import json,sys,pathlib
artifact,audit,output=map(pathlib.Path,sys.argv[1:])
def read(p,default):return json.loads(p.read_text()) if p.exists() else default
latest=read(artifact/'latest.json',{})
manual=read(audit/'manual-observations.json',{})
delivery=read(audit/'delivery-audit.json',{})
baseline=read(artifact/'baseline.json',{})
channels=['instagram','facebook','youtube','tiktok','pinterest','x']
profiles={'instagram':('Instagram','@mirai_skincaree','https://www.instagram.com/mirai_skincaree/'),'facebook':('Facebook','Mirai Skin','https://www.facebook.com/571704329368702'),'youtube':('YouTube','Mirai Skin',''),'tiktok':('TikTok','@mirai_skincare','https://www.tiktok.com/@mirai_skincare'),'pinterest':('Pinterest','Mirai Skin','https://www.pinterest.com/mirai_skin/'),'x':('X','@MiraiSkin7','https://x.com/MiraiSkin7')}
# Profile URLs are reviewed separately before release; post URLs are source evidence.
posts={}
for p in delivery.get('live_posts',[])+latest.get('posts',[]):
 key=(p['platform'],p.get('remote_post_url','').rstrip('/'))
 old=posts.get(key,{})
 posts[key]={**old,**p}
for platform in channels:
 for p in latest.get('sources',{}).get(platform,{}).get('posts',[]):
  key=(platform,p.get('remote_post_url','').rstrip('/'));posts[key]={**posts.get(key,{}),**p}
 for m in manual.get(platform,{}).get('posts',[]):
  for key,p in posts.items():
   if key[0]==platform and (p.get('remote_post_id') or p.get('remote_post_url','').rstrip('/').split('/')[-1])==m['remote_post_id'] and m.get('collected_at','')>p.get('collected_at',''):
    p.update(m)
allow=['views','impressions','reach','likes','comments','saves','shares','interactions','avg_watch_seconds','outbound_clicks','pin_clicks']
clean=[]
for p in posts.values():
 clean.append({'id':p['id'],'platform':p['platform'],'contentId':p.get('content_id',''),'title':p.get('title') or p.get('content_id',''),'url':p.get('remote_post_url',''),'publishedAt':p.get('published_at') or p.get('confirmed_at'),'dateBasis':'published' if p.get('published_at') else 'confirmed','observedAt':p.get('collected_at') or p.get('confirmed_at') or delivery.get('completed_at'),'source':p.get('source') or 'Verified publishing receipt','status':p.get('status','delivery_only'),'metrics':{k:v for k,v in p.get('metrics',{}).items() if k in allow},'note':p.get('note','')})
accounts=[]
for platform in channels:
 s=latest.get('sources',{}).get(platform,{})
 if manual.get(platform,{}).get('collected_at','')>s.get('collected_at',''):s={**s,**manual[platform]}
 name,handle,url=profiles[platform]
 accounts.append({'id':platform,'name':name,'handle':handle,'url':url,'followers':s.get('followers'),'observedAt':s.get('collected_at'),'baseline':baseline.get('followers',{}).get(platform),'baselineAt':baseline.get('followers_observed_at',{}).get(platform) or baseline.get('captured_at'),'mode':'manual' if platform in ['tiktok','pinterest'] else 'api_report','note': 'Native account check. Direct API metrics are not connected.' if platform in ['tiktok','pinterest'] else 'Collected by the existing Mirai cloud measurement workflow.'})
s=latest.get('sources',{}).get('shopify',{})
# No customer identifiers or order rows in the dashboard seed.
commerce={'observedAt':s.get('collected_at'),'start':s.get('since'),'end':s.get('until'),'currency':s.get('currency'),'status':s.get('status'),'sessions':[{k:r.get(k) for k in ['utm_source','utm_medium','utm_campaign','scope','sessions','sessions_with_cart_additions','sessions_that_reached_checkout','sessions_that_completed_checkout']} for r in s.get('sessions',[])],'orders':len(s['orders']['rows']) if isinstance(s.get('orders',{}).get('rows'),list) else None,'note':s.get('note','')}
# Aggregate order count is campaign-scoped; no channel/date splits are inferred.
report={'schemaVersion':1,'collectedAt':latest['collected_at'],'campaignStart':'2026-09-30','accounts':accounts,'posts':clean,'commerce':commerce,'delivery':{'observedAt':delivery.get('completed_at'),'queued':delivery.get('remaining_future'),'stories':delivery.get('stories_verified'),'held':delivery.get('held_for_ai_label_decision')},'evidenceUrl':'https://github.com/Kapi7/mirai-meta-campaign/actions/workflows/mirai-social-measurement.yml'}
output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
print('Wrote',len(accounts),'channels and',len(clean),'posts; collected',latest['collected_at'])
