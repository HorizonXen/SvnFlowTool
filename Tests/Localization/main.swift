import Foundation

@main struct LocalizationChecks {
    static func main() {
        UserDefaults.standard.setVolatileDomain([InterfaceLanguage.key: "zh-Hans"], forName: UserDefaults.argumentDomain)
        precondition(L("Update") == "更新")
        precondition(L("Working Copy") == "工作副本")
        precondition(T("{0} files", "{0} 个文件", 5) == "5 个文件")
        UserDefaults.standard.setVolatileDomain([InterfaceLanguage.key: "en"], forName: UserDefaults.argumentDomain)
        precondition(L("管理忽略项") == "Manage Hidden Items")
        precondition(L("Update") == "Update")
        precondition(L("/tmp/更新/My File.xlsx") == "/tmp/更新/My File.xlsx")
        precondition(T("{0} / {1}", "{1} / {0}", "literal {1}", "value") == "literal {1} / value")
        UserDefaults.standard.setVolatileDomain([InterfaceLanguage.key: "invalid"], forName: UserDefaults.argumentDomain)
        precondition(InterfaceLanguage.code == "zh-Hans")
        print("PASS: Chinese default/fallback, English switch, labels, counts and literal user values")
    }
}
