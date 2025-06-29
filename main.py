import requests, os, shlex, re, json, time, platform
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from datetime import datetime, timedelta

translation_table = str.maketrans({":": "：", "?": "？", "!": "！", "<": "《", ">": "》", "|": "_", "~": "～", "/": "_"})
MAX_RETRIES = 3

# 下载一个块（带重试）
def download_chunk_with_retry(url, start, end, part_num, headers, timeout=10):
    headers = headers.copy()
    headers['Range'] = f'bytes={start}-{end}'
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return part_num, response.content
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(1)
            else:
                print(f"❌ 分块 {part_num} 重试 {MAX_RETRIES} 次失败: {e}")
                return part_num, None

# 分块多线程下载一个文件
def download_file_multithread(url, filename, thread_count=4):
    headers = {}
    resp = requests.head(url)
    if 'Content-Length' not in resp.headers:
        print(f"❌ 无法获取文件大小: {url}")
        return False

    total_size = int(resp.headers['Content-Length'])
    block_size = total_size // thread_count

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = []
        for i in range(thread_count):
            start = block_size * i
            end = total_size - 1 if i == thread_count - 1 else start + block_size - 1
            futures.append(executor.submit(download_chunk_with_retry, url, start, end, i, headers))

        results = [None] * thread_count
        with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename, ncols=80) as pbar:
            for future in as_completed(futures):
                part_num, content = future.result()
                if content:
                    results[part_num] = content
                    pbar.update(len(content))
                else:
                    print(f"❌ 文件 {filename} 分块 {part_num} 下载失败，取消合并")
                    return False

    # 写入文件
    with open(filename, 'wb') as f:
        for part in results:
            f.write(part)

    print(f"✅ 下载完成: {filename}")
    return True


def eh_arc(gid, token):
    def convert_to_mib(value):
        match = re.match(r"([\d.]+)\s*(MiB|GiB|KiB)", value, re.IGNORECASE)
        if not match:
            return None  # 无法匹配格式，返回 None
        
        number, unit = match.groups()
        number = float(number)

        if unit.lower() == "gib":  # GiB 转换为 MiB
            number *= 1024
        elif unit.lower() == "kib":
            number /= 1024
        return int(number) if number.is_integer() else number
    url = f"https://exhentai.org/archiver.php?gid={gid}&token={token}"
    arc = requests.get(url=url, cookies=cookie)

    soup = BeautifulSoup(arc.text, 'html.parser')
    if soup == "This gallery is currently unavailable.":
        return "该画廊目前不可用"
    strong = soup.find_all('strong')
    original_size = convert_to_mib(strong[1].text)   # 原图大小
    resample_size = convert_to_mib(strong[3].text)   # 重彩样大小
    if strong[2].text == "Free!":
        resample_gp = round(resample_size / 0.062)
    elif strong[2].text == "N/A":
        resample_gp = "N/A"
    else:
        resample_gp = round(int(strong[2].text.split(" ")[0].replace(",", "")))
    if strong[0].text == "Free!":
        original_gp = round(original_size / 0.062)
    elif strong[0].text == "N/A":
        original_gp = "N/A"
    else:
        original_gp = round(int(strong[0].text.split(" ")[0].replace(",", "")))
    size = [original_size, resample_size]
    gp = [original_gp, resample_gp]
    return size, gp

def detection(gid,token,clarity,use_gp):
    # 检测是否有下载链接
    arc_url = "https://exhentai.org/archiver.php" + f"?gid={gid}" + f"&token={token}"
    response = requests.get(arc_url, cookies=cookie)
    soup = BeautifulSoup(response.text, 'html.parser')
    free = soup.find_all('strong')
    if not free[0].text == "Free!":
        url = f"https://{('e-hentai' if domain == '1' else 'exhentai')}.org/archiver.php?gid=3285545&token=7745b19f1e"
        response = requests.get(url, cookies=cookie)
        soup = BeautifulSoup(response.text, 'html.parser')
        for x in soup.find_all('p'):
            if "GP" in x.text and "Credits" in x.text:
                m_list = x.text.replace("[", "").replace("]", "").replace("?", "").replace(",", "").split()
                if m_list[0] - use_gp < 0:
                    return False, f"GP不足，GP还剩余{[m_list[0]]}，C还剩余{[m_list[2]]}"
                
    link = download_url(gid,token,clarity,cookie)
    if link[0] is True:
        while True:
            if requests.get(link[1]).status_code == 401:
                try:
                    if refresh_url(gid=gid, token=token, eh_cookie=cookie):
                        print("销毁成功")
                        link = download_url(gid,token,clarity,cookie)
                    else:    
                        return False, "链接销毁失败"
                except requests.exceptions.SSLError:
                    continue
                else:
                    break
    return link

def download_url(gid,token,clarity,eh_cookie):
    # 获取下载链接
    if clarity == "original":
        clarity = "Original"
        cc = "org"
    elif clarity == "resample":
        clarity = "Resample"
        cc = "res"
    payload = {
        "dltype": cc,
        "dlcheck": f"Download {clarity} Archive",  # 按钮对应的名字和按钮值
    }
    arc_url = f"https://{('e-hentai' if domain == '1' else 'exhentai')}.org/archiver.php?gid={gid}&token={token}"
    response = requests.post(arc_url, data=payload, cookies=eh_cookie)
    # 对下载原始图像进行post请求
    if response.status_code == 200:
        print("请求原始图像成功")
        if response.text != "You do not have enough funds to download this archive. Obtain some Credits or GP and try again.":
            soup = BeautifulSoup(response.text, 'html.parser')
            url = soup.find('a')["href"]
            link_original = url + "?start=1"
            return True, link_original
        elif "This IP address has been" in response.text:
            return False, "IP频率过高"
        else:
            return False, "GP不足"
    else:
        code = response.status_code
        print(f"请求原始图像失败，错误代码为：{code}")
        return False, code

def refresh_url(gid, token, eh_cookie):
    # 销毁下载链接
    payload = {
        "invalidate_sessions": 1,
    }
    arc_url = f"https://{('e-hentai' if domain == '1' else 'exhentai')}.org/archiver.php?gid={gid}&token={token}"
    response = requests.post(arc_url, data=payload, cookies=eh_cookie)
    if response.status_code == 200:
        return True
    else:
        return False


if os.path.exists("./config.json"):
    print("检测到配置文件...")
    try:
        with open("./config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
            domain = str(config['domain'])
            cookie = config['cookie']
            proxy = config['proxy']
            filename_rule = config['filename_rule']
            api = config['api']
            max_workers = config['max_workers']
            thread_count = config['thread_count']
            img = config['img']
    except Exception as e:
        input(f"导入配置文件出错，请删除配置文件...")
        exit
else:
    while True:
        domain = input("1.e-hentai\n2.exhentai\n请选择站点: ")
        if domain != "1" and domain != "2":
            print("请输入1或2")
        else:
            break
    cookie = {"ipb_member_id": input("请输入 ipb_member_id: "), "ipb_pass_hash": input("请输入 ipb_pass_hash: "), "igneous": input("请输入 igneous: ") if domain == "2" else ""}

    proxy = {"https": input("请输入代理地址(如: http://127.0.0.1:8787 , 没有则跳过): ")}

    filename_rule = input("请输入文件名规则:\n{gn}: 默认标题, {gj}: 日文标题, {gid}: gid, {post_utc_time}: utc上传时间, {post_shanghai_time}: 上海上传时间, {now_time}: 本地下载时间, {group}: 社团, {group_tra}: 社团翻译名\n如: https://exhentai.org/g/3329861/391f82d1ed 应用规则 {gid}_{gj}, 保存后为 3329861_[しまじや (しまじ)] エロRPGの女主人公にTS転生したら…～街エロイベント&敗北エッチで処女喪失～.zip\n如果加/的话那么就会作为路径\n为了防止文件名过长标题请只要一个\n请输入: ")
    api = input("是否下载api内的信息y/n(默认: n): ")

    max_workers = input("同时运行多少个任务(默认3): ")
    thread_count = input("每个任务多少线程(默认3): ")
    img = input("1. 原图\n2. 冲采样\n优先下载画质(默认原图):")

print("测试cookie中, 请稍等...")
try:
    ceshi = requests.get(url=f"https://{('e-hentai' if domain == '1' else 'exhentai')}.org/favorites.php", cookies=cookie, proxies=proxy, timeout=20)
except Exception as e:
    print(f"程序发生错误: {e}")
    input("")
    exit
if ceshi.status_code == 302:
    input("请检查cookie是否正确后重启软件...")
    exit
elif ceshi.url == "https://e-hentai.org/bounce_login.php?b=d&bt=1-6":
    input("请检查cookie是否正确后重启软件...")
    exit
elif ceshi.status_code == 200 and ceshi.text == "":
    input("请检查cookie是否正确后重启软件...")
    exit
else:
    print("cookie和网络均正常")
    download_path = input("请拖入下载文件夹或手动输入路径：")
    try:
        folder_path = shlex.split(download_path)[0]
        if os.path.isdir(folder_path):
            print("有效路径：", folder_path)
        else:
            input("路径无效或不是文件夹")
            exit
    except Exception as e:
        print("路径处理出错：", e)

    if os.path.exists("./downloads_urls.json"):
        print("检测到已有下载链接文件...")
        with open("./downloads_urls.json", 'r', encoding='utf-8') as f:
            download_urls = json.load(f)
    else:
        print("没有检测到下载链接，将开始获取...")
        soup = BeautifulSoup(ceshi.text, 'html.parser')
        favorites_ = [x.get("title") for x in soup.find_all('div', class_="i")]
        while True:
            favorites = input(f"{''.join([f'{y}. {x}\n' for x, y in zip(favorites_, range(0, len(favorites_) + 1))] + ['10. All\n'])}请选择需要下载的收藏夹: ")
            if not int(favorites) in range(0, 11):
                print("请输入0-10的数字")
            else:
                break

        url = f"https://{('e-hentai' if domain == '1' else 'exhentai')}.org/favorites.php?favcat={favorites}"
        download_urls = []
        while True:
            fav = requests.get(url=url, cookies=cookie, proxies=proxy, timeout=20)
            if fav.status_code == 200 and not fav.text == "":
                soup = BeautifulSoup(fav.text, 'html.parser')
                download_urls = download_urls + [x.find('a')['href'] for x in soup.find_all('td', class_="gl3c glname")]
            else:
                input("获取错误，请检查cookie...")
                exit
            if soup.find('a', class_="unext"):
                url = soup.find('a', class_="unext")['href']
            else:
                break
        with open("./downloads_urls.json", 'w', encoding='utf-8') as f:
            json.dump(download_urls, f, ensure_ascii=False)
        print(f"共有{len(download_urls)}个下载链接, 以导出到 {os.getcwd()}/downloads_urls.json")

    with ThreadPoolExecutor(max_workers=int(max_workers if max_workers else 3)) as executor:
        with open("./config.json", 'w', encoding='utf-8') as f:
            config = {"domain": domain, "cookie": cookie, "proxy": proxy, "api": api, "filename_rule": filename_rule, "max_workers": max_workers, "thread_count": thread_count, "img": img}
            json.dump(config, f, ensure_ascii=False)
        futures = []
        while True:
            try:
                tag_data = requests.get(requests.get(url="https://api.github.com/repos/EhTagTranslation/Database/releases/latest", proxies=proxy).json()['assets'][10]['browser_download_url'], proxies=proxy).json()
            except requests.exceptions.SSLError:
                continue
            else:
                break
        for task in download_urls:
            match = re.search(r"/g/(\d+)/([a-f0-9]+)/?", task)
            gid = match.group(1)
            token = match.group(2)
            data = {
                "method": "gdata",
                "gidlist": [
                    [gid,token]
                ],
                "namespace": 1
                }
            ss = requests.post(url="https://api.e-hentai.org/api.php", proxies=proxy, json=data)
            if ss.status_code ==200:
                data = ss.json()
                # language = tag_data['data'][2]['data'][data['gmetadata']]
                group = next((tag.split(":", 1)[1] for tag in data['gmetadata'][0]['tags'] if tag.startswith("group:")), "None")
                if group != "None":
                    group_tra = tag_data['data'][5]['data'][group]['name']
                else:
                    group_tra = "None"
                filename = (
                    filename_rule
                    .replace("{gn}", data['gmetadata'][0]['title'].translate(translation_table))
                    .replace("{gj}", data['gmetadata'][0]['title_jpn'].translate(translation_table))
                    .replace("{gid}", gid)
                    .replace("{post_utc_time}", datetime.fromtimestamp(int(data['gmetadata'][0]['posted'])).strftime('%Y-%m-%d-%H-%M'))
                    .replace("{post_shanghai_time}", (datetime.fromtimestamp(int(data['gmetadata'][0]['posted'])) + timedelta(hours=8)).strftime('%Y-%m-%d-%H-%M'))
                    .replace("{now_time}", datetime.now().strftime('%Y-%m-%d-%H-%M'))
                    .replace("{group}", group)
                    .replace("{group_tra}", group_tra)
                    + ".zip"
                )
                if platform.system() == "Windows":
                    if len(download_path + "/" + filename) > 260:
                        print(f"{task} 文件名长度过长，跳过")
                        continue
                else:
                    if len(filename) > 255:
                        print(f"{task} 文件名长度过长，跳过")
                        continue
                data = eh_arc(gid, token)
                if data == "该画廊目前不可用":
                    print("该画廊目前不可用")
                if img == "2":
                    if data[1][1] == "N/A":
                        link = detection(gid, token, "original", data[1][0])
                    else:
                        link = detection(gid, token, "resample", data[1][1])
                elif img == "1":
                    link = detection(gid, token, "original", data[1][0])

                if link[0] is True:
                    futures.append(executor.submit(
                        download_file_multithread,
                        link[1],
                        filename,
                        int(thread_count if thread_count else 3)
                    ))

        for future in as_completed(futures):
            success = future.result()
            if not success:
                print("❌ 某个任务下载失败")
