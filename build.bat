rmdir .\dist /Q /S
pyinstaller vizalerts.py --onefile --clean --workpath .\dist\work

mkdir .\dist\vizalerts
pushd .\dist\vizalerts
mkdir twilio
mkdir twilio\conf
mkdir config
mkdir docs
mkdir docs\media
mkdir demo
mkdir tests
mkdir logs
mkdir ops
mkdir vizalert
mkdir tabUtil
mkdir temp
popd

copy .\config\* .\dist\vizalerts\config /Y
copy .\docs\* .\dist\vizalerts\docs /Y
copy .\docs\media\* .\dist\vizalerts\docs\media /Y
copy .\demo\* .\dist\vizalerts\demo /Y
copy .\tests\* .\dist\vizalerts\tests /Y
copy .\logs\* .\dist\vizalerts\logs /Y
copy .\ops\* .\dist\vizalerts\ops /Y
copy .\vizalert\* .\dist\vizalerts\vizalert /Y
copy .\tabutil\* .\dist\vizalerts\tabUtil /Y
copy .\temp\* .\dist\vizalerts\temp /Y
copy .\tests\* .\dist\vizalerts\tests /Y
copy .\twilio\conf\* .\dist\vizalerts\twilio\conf /Y

copy .\version_history.txt .\dist\vizalerts /Y
copy .\LICENSE .\dist\vizalerts /Y
copy .\README.md .\dist\vizalerts /Y
copy .\vizalerts.py .\dist\vizalerts /Y
copy .\dist\vizalerts.exe .\dist\vizalerts\vizalerts.exe /Y

pandoc .\docs\install_guide.md -f markdown -t html -o  .\dist\vizalerts\docs\install_guide.html
pandoc .\docs\user_guide.md -f markdown -t html -o .\dist\vizalerts\docs\user_guide.html

7z a -r .\dist\vizalerts.zip .\dist\vizalerts\*