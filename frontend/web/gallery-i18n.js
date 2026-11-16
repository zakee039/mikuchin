// Gallery-specific UI strings; loaded after i18n-data, before i18n activation.
"use strict";
(() => {
  const dict = window.MIKUCHIN_TRANSLATIONS || {};
  Object.assign(dict["zh-CN"] || {}, {
    "Images":"生图", "Gallery":"画廊",
    "来源":"来源","排序":"排序","全部":"全部","生图":"生图",
    "最新优先":"最新优先","最旧优先":"最旧优先",
    "暂无生图记录":"暂无生图记录","加载更多":"加载更多",
    "全选已加载":"全选已加载","取消选择":"取消选择",
    "删除所选":"删除所选","仅查看此图":"仅查看此图",
    "NSFW · 内容已隐藏":"NSFW · 内容已隐藏"
  });
  Object.assign(dict["ja-JP"] || {}, {
    "Images":"画像生成","Gallery":"ギャラリー","来源":"ソース",
    "排序":"並び順","全部":"すべて","生图":"画像生成",
    "聊天":"チャット","本地模型":"ローカルモデル","API":"API",
    "最新优先":"新しい順","最旧优先":"古い順","刷新":"更新",
    "选择":"選択","已选择 0 张":"0 枚選択",
    "全选已加载":"表示分を全選択","取消选择":"選択を解除",
    "删除所选":"選択分を削除","标记为NSFW":"NSFW に設定","删除原图":"元画像を削除","删除4×":"4×画像を削除",
    "暂无生图记录":"画像がありません",
    "加载更多":"もっと見る","标记 NSFW":"NSFW に設定",
    "上一张":"前の画像","下一张":"次の画像","仅查看此图":"この画像だけ表示",
    "NSFW · 内容已隐藏":"NSFW · 非表示","查看图片":"画像ビューア",
    "删除":"削除","关闭":"閉じる"
  });
  Object.assign(dict["en-US"] || {}, {
    "Images":"Image Gen","Gallery":"Gallery","来源":"Source",
    "排序":"Sort","全部":"All","生图":"Image Gen",
    "聊天":"Chat","本地模型":"Local","API":"API",
    "最新优先":"Newest","最旧优先":"Oldest","刷新":"Refresh",
    "选择":"Select","已选择 0 张":"0 selected",
    "全选已加载":"Select loaded","取消选择":"Clear selection",
    "删除所选":"Delete selected","标记为NSFW":"Mark NSFW","删除原图":"Delete original","删除4×":"Delete 4×",
    "暂无生图记录":"No images yet",
    "加载更多":"Load more","标记 NSFW":"Mark NSFW",
    "上一张":"Previous","下一张":"Next","仅查看此图":"Reveal this image",
    "NSFW · 内容已隐藏":"NSFW · Hidden","查看图片":"Image viewer",
    "删除":"Delete","关闭":"Close"
  });
})();
