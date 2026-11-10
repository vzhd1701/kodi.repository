# repository.vzhd1701

## Publish add-on updates

1. Fix the add-on in its source repository, increase the version in its
   `addon.xml`, and commit and push those changes to its `master` branch.
2. Open [Actions → Update add-ons](https://github.com/vzhd1701/kodi.repository/actions/workflows/update-addons.yml).
3. Click **Run workflow**, select **master**, and click **Run workflow** again.
4. Wait for a green check mark. The action commits and pushes the new packages,
   catalog, and catalog checksum. Kodi can then discover the update.

The action checks the public GitHub repositories listed in
[`addon-sources.json`](addon-sources.json). It builds ZIPs only when the source
`addon.xml` has a newer version than the published catalog. If all versions are
current, it makes no commit. Changing code without increasing the version does
not publish an update. Versions must be stable dotted numbers, such as `0.0.4`.

The list records each add-on's ID, GitHub `owner/repository`, branch, and folder
containing `addon.xml`. Add another entry to include another add-on. Existing
catalog entries not in the list, including the repository installer, stay intact.
Published ZIPs are kept, and existing release files are never overwritten.

The workflow uses GitHub's built-in token with `contents: write`; no additional
secret is needed for these public source repositories. Branch rules must allow
the workflow to push to `master`. The workflow runs manually and only on `master`,
because that is the branch used by the installed Kodi repository.

### Run locally (Python 3.9 or newer and Git)

```powershell
python -m unittest discover -s tests -v
python scripts/update_addons.py
```

The local script builds files but does not commit or push. To build from a local
Kinoman checkout instead of downloading its published source:

```powershell
python scripts/update_addons.py --source plugin.video.kinomanuz=C:\Projects\plugin.video.kinomanuz
```

Only Git-tracked files inside the add-on's folder enter the ZIP. Source code is
packaged without running it. All source downloads and package validation finish
before the catalog is changed; failures stop the workflow before its publish step.

The previous packaging batch file is no longer needed for this workflow.

Тут находится репозиторий моих расширений для медиаплеера [**Kodi**](https://kodi.tv)

## Как установить

1.  Скачать установочный архив репозитория [по этой ссылке](https://kodi.vzhd1701.com)
2.  Переместить скачанный файл **repository.vzhd1701-2.0.0.zip** на устройство или в сетевую папку доступную из **Kodi**
3.  Открыть **Kodi** и выбрать пункт **Дополнения**
4.  Нажать иконку коробки (как на [картинке](https://imgur.com/a/h2gk2GX))
5.  Выбрать пункт **Установить из файла ZIP**
6.  Выбрать скачанный файл **repository.vzhd1701-2.0.0.zip**

**Внимание!** Возможно придется разрешить установку из **неизвестных источников**

1.  В открывшемся сообщении нажмите кнопку **Настройки**
2.  Включите опцию **Неизвестные источники** и подтвердите выбор
3.  Вернитесь обратно и продолжите установку репозитория
