# Spike (ADR-0012): compares one-call upstream previews with our snapshot. Usage: backend/.venv/bin/python -I scripts/spikes/cold_first_page_probe.py .env <org>  (needs the stack running on :18000)
import asyncio, os, sys, time, httpx, json
tok = next(l.split("=",1)[1].strip() for l in open(sys.argv[1]) if l.startswith("GITHUB_TOKEN="))
H = {"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"telescope-spike"}
A = dict(H, Authorization=f"Bearer {tok}")
B = "https://api.github.com"
async def t(c, label, coro):
    s=time.perf_counter(); r=await coro; d=time.perf_counter()-s
    print(f"{label:55s} {r.status_code} {d*1000:6.0f}ms {len(r.content)/1024:7.0f}KiB rl={r.headers.get('x-ratelimit-resource')}:{r.headers.get('x-ratelimit-remaining')}")
    return r
async def main():
    org = sys.argv[2]
    async with httpx.AsyncClient(timeout=30) as c:
        for auth,h in (("anon",H),("token",A)):
            await t(c,f"[{auth}] REST list p1 full_name x100", c.get(f"{B}/orgs/{org}/repos",params=dict(type="public",sort="full_name",per_page=100,page=1),headers=h))
        await t(c,"[token] REST list p1 x30", c.get(f"{B}/orgs/{org}/repos",params=dict(type="public",sort="full_name",per_page=30),headers=A))
        r = await t(c,"[token] REST list sort=updated desc x100", c.get(f"{B}/orgs/{org}/repos",params=dict(type="public",sort="updated",direction="desc",per_page=100),headers=A))
        upd = [x["full_name"] for x in r.json()][:30]
        r = await t(c,"[token] REST list sort=pushed desc x100", c.get(f"{B}/orgs/{org}/repos",params=dict(type="public",sort="pushed",direction="desc",per_page=100),headers=A))
        push = [x["full_name"] for x in r.json()][:30]
        for auth,h in (("anon",H),("token",A)):
            r = await t(c,f"[{auth}] SEARCH org: fork:true sort=stars x30", c.get(f"{B}/search/repositories",params=dict(q=f"org:{org} fork:true",sort="stars",order="desc",per_page=30),headers=h))
        sj = r.json(); print("   search total_count", sj.get("total_count"), "incomplete", sj.get("incomplete_results"))
        search_stars = [x["full_name"] for x in sj["items"]]
        q = """query($o:String!){organization(login:$o){repositories(first:100,privacy:PUBLIC,orderBy:{field:STARGAZERS,direction:DESC}){totalCount nodes{databaseId nameWithOwner stargazerCount isFork isArchived pushedAt updatedAt primaryLanguage{name}}}}}"""
        r = await t(c,"[token] GRAPHQL repos orderBy STARGAZERS x100", c.post(f"{B}/graphql",json=dict(query=q,variables=dict(o=org)),headers=A))
        gj = r.json(); print("   gql totalCount", gj["data"]["organization"]["repositories"]["totalCount"])
        gql_stars = [n["nameWithOwner"] for n in gj["data"]["organization"]["repositories"]["nodes"]][:30]
        r = await t(c,"[anon] GRAPHQL (expect 401)", c.post(f"{B}/graphql",json=dict(query=q,variables=dict(o=org)),headers=H))
        # authoritative from our running api
        ours = {}
        for s in ("stars","updated","pushed"):
            rr = await c.get(f"http://localhost:18000/api/orgs/{org}/repos",params=dict(sort=s,limit=30),timeout=120)
            ours[s] = [x["full_name"] for x in rr.json()["items"]]
        def cmp(name,a,b): print(f"   {name:28s} exact-order={a==b} overlap={len(set(a)&set(b))}/30")
        cmp("search stars vs ours", search_stars, ours["stars"])
        cmp("graphql stars vs ours", gql_stars, ours["stars"])
        cmp("REST updated vs ours", upd, ours["updated"])
        cmp("REST pushed vs ours", push, ours["pushed"])
        if search_stars != ours["stars"]:
            for i,(a,b) in enumerate(zip(search_stars,ours["stars"])):
                if a!=b: print("   first diff @",i,a,b); break
asyncio.run(main())
