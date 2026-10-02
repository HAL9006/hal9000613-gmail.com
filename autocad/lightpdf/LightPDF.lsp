;;; ===================================================================
;;; LightPDF.lsp  -  Acrobat「PDFを編集」が速く開く最軽量PDFを出力する
;;; TASK-20261002-autolisp-lightpdf
;;;
;;; コマンド : LIGHTPDF
;;; 出力先   : 図面と同じフォルダに <図面名>_light.pdf
;;;            （同名ファイルがあれば _1, _2 ... を付け、既存PDFは上書きしない）
;;;
;;; 処理の流れ
;;;   1. 現在の状態（システム変数・画層の印刷可否・文字スタイルのフォント）を保存
;;;   2. 重い画層（ハッチング等）を「印刷しない」に一時変更
;;;   3. SHX フォントの文字スタイルを一時的に TrueType へ差し替え
;;;   4. -PLOT で Smallest File 系 PC3 から PDF を出力（前景印刷）
;;;   5. 保存しておいた状態へ必ず復元（エラー・ESC 中断時も *error* で復元）
;;;
;;; 図面ファイル(.dwg)は保存しない。変更はすべてメモリ上の一時変更で、
;;; 出力後に元へ戻す。UNDO も 1 グループにまとめる。
;;; ===================================================================

(vl-load-com)

;;;; ------------------------------------------------------------------
;;;; 設定（環境に合わせてここだけ書き換える）
;;;; ------------------------------------------------------------------

;; [Acrobat軽量化 #1] 出力ドライバ
;; Smallest File は「ベクター品質を下げる＋余計なデータを含めない」プリセット。
;; Acrobat が解析するパス（ベクター点列）の精度と量が減るため、
;; 「PDFを編集」時の解析時間が短くなる。
;; INSTALL.md の手順で作るカスタム版（LightPDF.pc3）を使う場合は名前を差し替える。
(setq *LP:PC3* "AutoCAD PDF (Smallest File).pc3")

;; 用紙（PC3 に存在する名前をそのまま書く。-PLOT の [?] で一覧表示できる）
(setq *LP:Paper* "ISO full bleed A3 (420.00 x 297.00 MM)")

;; 用紙の向き  "_L" = 横 / "_P" = 縦
(setq *LP:Orient* "_L")

;; 印刷スタイル  "" = 現在の設定のまま / "monochrome.ctb" など
(setq *LP:CTB* "monochrome.ctb")

;; [Acrobat軽量化 #2] 印刷しない画層（大文字で記述・カンマ区切りのワイルドカード）
;; ハッチングは 1 つで数百〜数千本の線分になり、Acrobat の解析負荷の大半を占める。
;; ここに一致する画層を出力時だけ「印刷しない」にする（画面表示は変えない）。
(setq *LP:HeavyLayers* "*HATCH*,*ハッチ*,*PATTERN*,*塗*,*網掛*")

;; [Acrobat軽量化 #3] SHX の代わりに使う TrueType フォント
;; SHX 文字は PDF 上では「1 文字＝多数の線分」として出力され、
;; Acrobat には文字ではなく大量のベクターとして見える。
;; TrueType に置き換えると PDF 内で本物の「テキスト」になり、
;; 解析対象のパスが激減する上、Acrobat で文字として編集・検索できる。
(setq *LP:TTF* "msgothic.ttc")

;; 出力ファイル名の接尾辞
(setq *LP:Suffix* "_light")

;;;; ------------------------------------------------------------------
;;;; 補助関数
;;;; ------------------------------------------------------------------

;; SHX フォントか（拡張子なし も SHX として扱われる）
(defun LP:shx-p (ff / ext)
  (and ff
       (/= ff "")
       (or (null (setq ext (vl-filename-extension ff)))
           (= (strcase ext) ".SHX"))))

;; 既存ファイルを上書きしない出力パスを作る
(defun LP:unique-pdf (base / n f)
  (setq n 0
        f (strcat base ".pdf"))
  (while (findfile f)
    (setq n (1+ n)
          f (strcat base "_" (itoa n) ".pdf")))
  f)

;; システム変数の保存／復元（存在しない変数は飛ばす）
(defun LP:sv-save (names / v out)
  (foreach n names
    (if (setq v (getvar n))
      (setq out (cons (cons n v) out))))
  out)

(defun LP:sv-restore (lst)
  (foreach p lst
    (vl-catch-all-apply 'setvar (list (car p) (cdr p)))))

(defun LP:sv-set (name val)
  (if (getvar name)
    (vl-catch-all-apply 'setvar (list name val))))

;; [Acrobat軽量化 #2] 重い画層を「印刷しない」に。元の値を ((画層 . 印刷可否) ...) で返す
(defun LP:hide-heavy (doc / out)
  (vlax-for lay (vla-get-Layers doc)
    (if (and (wcmatch (strcase (vla-get-Name lay)) *LP:HeavyLayers*)
             (= (vla-get-Plottable lay) :vlax-true))
      (progn
        (setq out (cons (cons lay (vla-get-Plottable lay)) out))
        (vl-catch-all-apply 'vla-put-Plottable (list lay :vlax-false)))))
  out)

(defun LP:restore-layers (lst)
  (foreach p lst
    (vl-catch-all-apply 'vla-put-Plottable (list (car p) (cdr p)))))

;; [Acrobat軽量化 #3] SHX の文字スタイルを TrueType へ一時差し替え。
;; 元の値を ((スタイル 元FontFile 元BigFontFile) ...) で返す
(defun LP:ttf-styles (doc / out ff bf)
  (vlax-for st (vla-get-TextStyles doc)
    (setq ff (vla-get-FontFile st)
          bf (vla-get-BigFontFile st))
    (if (and (/= (vla-get-Name st) "")          ; 形状(shape)定義用の無名スタイルは対象外
             (LP:shx-p ff)
             (not (vl-catch-all-error-p
                    (vl-catch-all-apply 'vla-put-FontFile (list st *LP:TTF*)))))
      (progn
        (setq out (cons (list st ff bf) out))
        ;; TrueType にはビッグフォントが無いので外す
        (vl-catch-all-apply 'vla-put-BigFontFile (list st "")))))
  out)

(defun LP:restore-styles (lst)
  (foreach r lst
    (vl-catch-all-apply 'vla-put-FontFile (list (car r) (cadr r)))
    (vl-catch-all-apply 'vla-put-BigFontFile (list (car r) (caddr r)))))

;; -PLOT 詳細設定（モデル／レイアウトで質問の順番が違う）
(defun LP:plot (pdf)
  (if (= (getvar "TILEMODE") 1)
    ;; モデル空間：図形範囲を用紙にフィット・中央配置
    (command "_.-PLOT"
             "_Y"          ; 詳細な印刷設定
             ""            ; 現在のレイアウト(Model)
             *LP:PC3*      ; 出力デバイス
             *LP:Paper*    ; 用紙サイズ
             "_M"          ; 単位 mm
             *LP:Orient*   ; 向き
             "_N"          ; 上下反転しない
             "_E"          ; 印刷範囲＝図形範囲
             "_F"          ; 尺度＝用紙にフィット
             "_C"          ; 中央に印刷
             "_Y"          ; 印刷スタイルを使う
             *LP:CTB*      ; 印刷スタイルテーブル
             "_Y"          ; 線の太さを印刷
             ""            ; 陰影印刷＝表示どおり
             pdf           ; 出力ファイル名
             "_N"          ; ページ設定の変更を保存しない（図面を変更しない）
             "_Y")         ; 印刷実行
    ;; レイアウト（ペーパー空間）：レイアウトを 1:1 で
    (command "_.-PLOT"
             "_Y" "" *LP:PC3* *LP:Paper* "_M" *LP:Orient* "_N"
             "_L"          ; 印刷範囲＝レイアウト
             "1:1"         ; 尺度
             "0,0"         ; 印刷オフセット
             "_Y" *LP:CTB* "_Y"
             "_N"          ; 線の太さを尺度に合わせない
             "_N"          ; ペーパー空間を最後に印刷
             "_N"          ; ペーパー空間オブジェクトの隠線処理なし
             pdf "_N" "_Y")))

;;;; ------------------------------------------------------------------
;;;; コマンド本体
;;;; ------------------------------------------------------------------

(defun c:LIGHTPDF (/ *error* LP:restore-all doc sv lays sts pdf)
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object)))

  ;; 状態の復元（正常終了・エラー・ESC のどこからでも 1 回だけ実行）
  (defun LP:restore-all ()
    (if sts  (progn (LP:restore-styles sts) (setq sts nil)))
    (if lays (progn (LP:restore-layers lays) (setq lays nil)))
    (if sv   (progn (LP:sv-restore sv) (setq sv nil)))
    (vl-catch-all-apply 'vla-Regen (list doc acAllViewports))
    (vl-catch-all-apply 'vla-EndUndoMark (list doc)))

  (defun *error* (msg)
    (LP:restore-all)
    (if (and msg (not (wcmatch (strcase msg) "*CANCEL*,*QUIT*,*キャンセル*")))
      (princ (strcat "\n[LightPDF] エラー: " msg " / 図面の状態は元に戻しました。")))
    (princ))

  (cond
    ((= (getvar "DWGTITLED") 0)
     (princ "\n[LightPDF] 図面を一度保存してから実行してください（出力先フォルダが決まらないため）。"))
    (T
     (vla-StartUndoMark doc)
     (setq pdf (LP:unique-pdf
                 (strcat (getvar "DWGPREFIX")
                         (vl-filename-base (getvar "DWGNAME"))
                         *LP:Suffix*)))

     ;; 1. 状態保存
     (setq sv (LP:sv-save '("CMDECHO" "BACKGROUNDPLOT" "TEXTFILL" "PDFSHX")))

     (LP:sv-set "CMDECHO" 0)
     ;; 前景印刷にしないと、印刷完了前に復元処理が走って設定が崩れる
     (LP:sv-set "BACKGROUNDPLOT" 0)
     ;; TrueType 文字を塗りつぶしで出力（輪郭線化させない）
     (LP:sv-set "TEXTFILL" 1)
     ;; [Acrobat軽量化 #4] SHX 文字を「注釈(コメント)」として PDF に埋め込まない。
     ;; 1 にすると SHX 1 文字ごとに注釈オブジェクトが増え、Acrobat の処理が重くなる。
     (LP:sv-set "PDFSHX" 0)

     ;; 2〜3. 一時変更
     (setq lays (LP:hide-heavy doc))
     (setq sts  (LP:ttf-styles doc))
     (vla-Regen doc acAllViewports)

     ;; 4. 出力
     (princ (strcat "\n[LightPDF] 印刷しない画層: " (itoa (length lays))
                    " / TrueType化した文字スタイル: " (itoa (length sts))))
     (LP:plot pdf)

     ;; 5. 復元
     (LP:restore-all)

     (if (findfile pdf)
       (princ (strcat "\n[LightPDF] 出力完了: " pdf))
       (princ "\n[LightPDF] PDF が作成されませんでした。PC3名・用紙名を確認してください（INSTALL.md 参照）。"))))
  (princ))

(princ "\n[LightPDF] 読み込み完了。コマンド LIGHTPDF で最軽量PDFを出力します。")
(princ)
