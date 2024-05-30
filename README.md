# 崩坏：星穹铁道 - 数据扫描

使用OCR技术，可以轻松将崩坏：星穹铁道中的光锥、遗物和角色数据导出为JSON格式。

导出的结果可以用于各种社区制作的优化工具，包括：

- [Fribbels HSR Optimizer](https://fribbels.github.io/hsr-optimizer/)
- [Relic Harmonizer](https://relicharmonizer.com/)

本fork版本为汉化版。

## 安装

[下载最新版本的HSR Scanner](https://github.com/kel-z/HSR-Scanner/releases/latest)，然后以管理员身份运行（需要模拟键盘和鼠标按键）。

<!-- If you haven't already, download and install [Microsoft Visual C++ Redistributable for Visual Studio 2015-2022](https://docs.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170#visual-studio-2015-2017-2019-and-2022) (x86 or x64 depending on system). -->

## 操作步驟

1. 将游戏文字语言设置为英语。
2. 将游戏分辨率设置为16:9的比例（例如1920x1080、1280x720）。
3. **在星穹铁道中，避开明亮的颜色。** _是的，真的。_ 库存界面是半透明的，明亮的颜色可能会透过来，使文本更难准确检测和识别。在大多数情况下，向地面看去通常有效，只要屏幕的右侧相对较暗即可。（通过打开库存页面并查看右侧的物品信息是否与背景有良好的对比来进行二次确认。）如果只扫描角色，则可以跳过此步骤。
   ![Dark background example](./example.png)
4. 打开手机菜单（ESC菜单）。
5. 在HSR Scanner中配置必要的[扫描器设置](#scanner-settings-and-configurations)。
6. 开始扫描。
7. 在扫描过程中不要移动鼠标。
8. 扫描完成后，可能需要额外的时间来处理数据，然后生成最终的JSON文件输出。

截至`v0.3.0`，该应用的数据库与本存储库[分开更新](https://github.com/kel-z/HSR-Data)。如果数据库版本与最新游戏版本不匹配，则数据库尚未更新。

## 扫描设置和配置

HSR Scanner具有以下扫描选项：

- 选择是否扫描光锥、遗物和/或角色。
- 在JSON文件中包含UID（默认情况下禁用）。
- 设置JSON文件的输出位置。
- 根据最低稀有度或等级阈值筛选光锥、遗物和角色。

如果星穹铁道在您的系统上出现卡顿，扫描器可能会执行输入动作过快，导致游戏无法及时响应或重新渲染。为了解决这个问题，在配置选项卡中可以增加两种类型的延迟：

- 导航延迟，用于在不同页面之间导航（库存、角色详情等）。
- 扫描延迟，用于在单个项目（遗物、光锥和角色）之间点击。

扫描器默认使用 `b` 和 `c` 分别导航到库存和角色屏幕。如果您更改了这些热键，您需要在配置选项卡中更新相应的键。

如果启用了调试模式，则扫描器将会将在扫描过程中拍摄的所有截图保存到指定输出目录中的debug文件夹中。

## 输出

输出部分基本上是基于原神的`.GOOD`导出格式。我不希望这个输出很快就会改变。如果必须对输出进行重大更改，则版本号将增加一个，以便与之前的版本区别开来。

### 注意事项

- SPD副属性有一个扫描器无法直接解析的隐藏小数点。因此，重新生成角色属性（例如在优化网站上）很可能会将您的SPD属性值显示为比游戏内显示的更低。这不是扫描器的问题，而是通过OCR获取副属性时的限制。
- 如果在扫描或之前的扫描中无法确定Trailblazer变种，则默认为`Stelle`。
- 平面副属性和百分比副属性在键名后面会用下划线进行区分。
  - 主属性永远不会有下划线后缀。
- 副属性按顺序排序：`HP，ATK，DEF，HP%，ATK%，DEF%，SPD，CRIT Rate，CRIT DMG，Effect Hit Rate，Effect RES，Break Effect`。这个排序适用于除新升级的遗物外的每个遗物，当用户登出并重新登录时，这些遗物的排序会得到修复。因此，扫描器会在生成输出前自动对副属性进行排序。
- 光锥和遗物的`_id`值在扫描过程中被随机分配。这意在便于在扫描过程中记录任何错误时进行查找，进行二次确认或手动修正。
- 对于`Dan Heng • Imbibitor Lunae`，JSON输出中的字符`•`将显示为`\u2022`。这是特殊字符包含在JSON中时的Unicode表示法，是JSON中包含特殊字符时的正常行为。大多数现代环境在显示或处理JSON时会自动将`\u2022`呈现为`•`。
- 对于角色迹记，`ability_#`和`stat_#`是按照最早可解锁等级的顺序排序（例如，`stat_1`可以在0阶解锁，但`stat_2`需要2阶）。
  - 如果有并列的情况，即两个相同阶解锁但Visually连接到游戏角色迹记页面上最高`stat_#`的属性奖励_X_和_Y_，则_X_放在前面，_Y_放在后面。例如，如果属性奖励_X_连接到`stat_2`，而属性奖励_Y_连接到`stat_1`，那么_X_将成为`stat_3`，_Y_将成为`stat_4`。
    - 如果_X_和_Y_都连接到相同的`stat_#`（仅在Erudition中发现），则从下到上进行视觉分配。
- 使用的确切字符串值可以在[这里](src/models/game_data.py)找到。

当前输出示例：
```JSON
{
    "source": "HSR-Scanner",
    "build": "v1.0.0",
    "version": 3,
    "metadata": {
        "uid": 601869216,
        "trailblazer": "Stelle"
    },
    "light_cones": [
        {
            "key": "Cruising in the Stellar Sea",
            "level": 60,
            "ascension": 4,
            "superimposition": 2,
            "location": "Seele",
            "lock": true,
            "_id": "light_cone_1"
        },
        {
            "key": "Meshing Cogs",
            "level": 1,
            "ascension": 0,
            "superimposition": 5,
            "location": "",
            "lock": true,
            "_id": "light_cone_2"
        }
    ],
    "relics": [
        {
            "set": "Celestial Differentiator",
            "slot": "Planar Sphere",
            "rarity": 5,
            "level": 15,
            "mainstat": "Wind DMG Boost",
            "substats": [
                {
                    "key": "HP",
                    "value": 105
                },
                {
                    "key": "CRIT Rate_",
                    "value": 3.2
                },
                {
                    "key": "CRIT DMG_",
                    "value": 17.4
                },
                {
                    "key": "Effect Hit Rate_",
                    "value": 8.2
                }
            ],
            "location": "Bronya",
            "lock": true,
            "discard": false,
            "_id": "relic_1"
        },
        {
            "set": "Thief of Shooting Meteor",
            "slot": "Body",
            "rarity": 4,
            "level": 0,
            "mainstat": "Outgoing Healing Boost",
            "substats": [
                {
                    "key": "HP",
                    "value": 30
                },
                {
                    "key": "HP_",
                    "value": 3.4
                }
            ],
            "location": "",
            "lock": false,
            "discard": true,
            "_id": "relic_2"
        }
    ],
    "characters": [
        {
            "key": "Seele",
            "level": 59,
            "ascension": 4,
            "eidolon": 0,
            "skills": {
                "basic": 4,
                "skill": 6,
                "ult": 6,
                "talent": 6
            },
            "traces": {
                "ability_1": true,
                "ability_2": true,
                "ability_3": false,
                "stat_1": true,
                "stat_2": true,
                "stat_3": true,
                "stat_4": true,
                "stat_5": true,
                "stat_6": false,
                "stat_7": false,
                "stat_8": false,
                "stat_9": false,
                "stat_10": false
            }
        },
        {
            "key": "Bronya",
            "level": 20,
            "ascension": 1,
            "eidolon": 0,
            "skills": {
                "basic": 1,
                "skill": 1,
                "ult": 1,
                "talent": 1
            },
            "traces": {
                "ability_1": true,
                "ability_2": false,
                "ability_3": false,
                "stat_1": true,
                "stat_2": false,
                "stat_3": false,
                "stat_4": false,
                "stat_5": false,
                "stat_6": false,
                "stat_7": false,
                "stat_8": false,
                "stat_9": false,
                "stat_10": false
            }
        }
    ]
}
```

检查 [sample_output.json](sample_output.json) 以获取完整大小的、未过滤的示例。

---

HSR-Scanner 不隶属于 HoYoverse，也不受其认可、赞助或批准。
