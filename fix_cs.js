const fs = require('fs');
const path = 'languages/chinese-simplified/resource.rc';
let content = fs.readFileSync(path, 'utf-8');

// Fix resize dialog - read the actual file content
const oldBlock = content.substring(content.indexOf('IDD_PV_RESIZE'), content.indexOf('IDD_LOG'));

const newBlock = IDD_PV_RESIZE DIALOG DISCARDABLE  0, 0, 216, 132
STYLE DS_MODALFRAME | DS_NOIDLEMSG | WS_POPUP | WS_CAPTION | WS_SYSMENU
CAPTION "调整大小"
FONT 9, "MS Shell Dlg"
BEGIN
    CONTROL         "像素",IDC_PV_RESIZE_RADIO_PX,"Button",
                    BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP,8,8,60,10
    CONTROL         "百分比",IDC_PV_RESIZE_RADIO_PCT,"Button",
                    BS_AUTORADIOBUTTON,80,8,70,10
    LTEXT           "宽度",IDC_STATIC,8,26,90,8
    LTEXT           "高度",IDC_STATIC,120,26,90,8
    EDITTEXT        IDC_PV_RESIZE_EDIT_W,8,36,90,14,ES_AUTOHSCROLL | 
                    ES_NUMBER | WS_GROUP
    EDITTEXT        IDC_PV_RESIZE_EDIT_H,120,36,90,14,ES_AUTOHSCROLL | 
                    ES_NUMBER
    CONTROL         "保持纵横比",IDC_PV_RESIZE_KEEPRATIO,"Button",
                    BS_AUTOCHECKBOX | WS_GROUP | WS_TABSTOP,8,56,120,10
    LTEXT           "当前:",IDC_PV_RESIZE_STATIC_CUR,8,76,204,9
    LTEXT           "新:",IDC_PV_RESIZE_STATIC_NEW,8,88,204,9
    DEFPUSHBUTTON   "OK",IDOK,104,110,50,14,WS_GROUP
    PUSHBUTTON      "Cancel",IDCANCEL,158,110,50,14
END
;

content = content.replace(oldBlock, newBlock + '\r\n');
fs.writeFileSync(path, content, 'utf-8');
console.log('Done');
