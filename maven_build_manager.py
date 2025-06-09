import os
import sys
import subprocess
import xml.etree.ElementTree as ET
import configparser
import platform
import re
from PyQt5 import QtWidgets, QtCore

def update_config_file(filename, section, updates):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        lines = []
    
    new_lines = []
    in_section = False
    section_found = False
    updated_keys = set()
    section_header_regex = re.compile(r'^\s*\[([^\]]+)\]')
    for line in lines:
        match = section_header_regex.match(line)
        if match:
            current_section = match.group(1).strip()

            if in_section:
                for k, v in updates.items():
                    if k not in updated_keys:
                        new_lines.append(f"{k} = {v}\n")
                updated_keys.clear()
                in_section = False

            if current_section == section:
                in_section = True
                section_found = True
                new_lines.append(line)
                continue
            else:
                new_lines.append(line)
                continue
            
        if in_section:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", ";")) and "=" in line:
                key_part = line.split("=", 1)[0].strip()
                if key_part in updates:
                    new_lines.append(f"{key_part} = {updates[key_part]}\n")
                    updated_keys.add(key_part)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not section_found:
        new_lines.append(f"\n[{section}]\n")
        for k, v in updates.items():
            new_lines.append(f"{k} = {v}\n")
    elif in_section:
        for k, v in updates.items():
            if k not in updated_keys:
                new_lines.append(f"{k} = {v}\n")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print("Fehler beim Speichern der Konfiguration:", e)

class MavenProject:
    def __init__(self, path):
        self.path = path
        self.artifactId = None
        self.groupId = None
        self.java_version = None
        self._read_pom()

    def _read_pom(self):
        pom_file = os.path.join(self.path, "pom.xml")
        if os.path.exists(pom_file):
            try:
                tree = ET.parse(pom_file)
                root = tree.getroot()
                ns = ""
                if "}" in root.tag:
                    ns = root.tag.split("}")[0] + "}"
                # ArtifactId (as project name)
                artifact_elem = root.find(f"{ns}artifactId")
                self.artifactId = artifact_elem.text.strip() if artifact_elem is not None else os.path.basename(self.path)
                # GroupId (as name)
                group_elem = root.find(f"{ns}groupId")
                self.groupId = group_elem.text.strip() if group_elem is not None else "unbekannt"
                # Java-Version from the properties (<maven.compiler.source>)
                properties_elem = root.find(f"{ns}properties")
                if properties_elem is not None:
                    version_elem = properties_elem.find(f"{ns}maven.compiler.source")
                    self.java_version = version_elem.text.strip() if version_elem is not None else "Unbekannt"
                else:
                    self.java_version = "Unbekannt"
            except Exception as e:
                self.artifactId = os.path.basename(self.path)
                self.groupId = "Fehler"
                self.java_version = f"Fehler: {e}"
        else:
            self.artifactId = os.path.basename(self.path)
            self.groupId = "Nicht gefunden"
            self.java_version = "Keine pom.xml gefunden"

class MavenBuildWorker(QtCore.QThread):
    build_output = QtCore.pyqtSignal(str)

    def __init__(self, command, project_path):
        super().__init__()
        self.command = command
        self.project_path = project_path
        self.process = None
        self._isCanceled = False

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.project_path,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            while True:
                line = self.process.stdout.readline()
                if line:
                    self.build_output.emit(line)
                else:
                    break
                if self._isCanceled:
                    break
            self.process.stdout.close()
            retcode = self.process.wait()
            if self._isCanceled:
                self.build_output.emit("Build abgebrochen.\n")
            else:
                self.build_output.emit("Build abgeschlossen.\n")
        except Exception as e:
            self.build_output.emit(f"Fehler beim Build: {e}")

    def cancel(self):
        self._isCanceled = True
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass

class ProjectLoaderWorker(QtCore.QThread):
    project_found = QtCore.pyqtSignal(object)
    
    def __init__(self, base_dir, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        
    def run(self):
        if os.path.isdir(self.base_dir):
            for root_dir, dirs, files in os.walk(self.base_dir):
                if "pom.xml" in files:
                    pom_path = os.path.join(root_dir, "pom.xml")
                    try:
                        tree = ET.parse(pom_path)
                        pom_root = tree.getroot()
                        ns = ""
                        if "}" in pom_root.tag:
                            ns = pom_root.tag.split("}")[0] + "}"
                        
                        # Do not use projects with parent tag
                        if pom_root.find(f"{ns}parent") is not None:
                            # If a parent-Tag is found, continue and search for the next pom.xml
                            continue 
                        
                        project = MavenProject(root_dir)
                        self.project_found.emit(project)
                        
                        # When a project is found, we clear the directory listing to prevent os.walk from running to the subfolders
                        dirs[:] = []
                        
                    except ET.ParseError:
                        print(f"Error parsing {pom_path}: Not a valid XML file.")
                        pass
                    except Exception as e:
                        print(f"An unexpected error occurred with {pom_path}: {e}")
                        pass

class MavenBuildGUI(QtWidgets.QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        # Saved maven projects
        self.projects = []
        # Running build-worker
        self.worker = None
        self._initUI()
        # Load last build options
        self._loadLastState()

    def _initUI(self):
        self.setWindowTitle("Maven Build Manager | v.0.16 © 2025 by magicmarcy")
        self.resize(900, 900)
        
        tab_widget = QtWidgets.QTabWidget()
        
        # --- Tab 1: maven projects & build optionen ---
        tab_projects = QtWidgets.QWidget()
        projects_layout = QtWidgets.QVBoxLayout(tab_projects)
        
        lbl_projects = QtWidgets.QLabel("Gefundene Maven Projekte:")
        projects_layout.addWidget(lbl_projects)
        
        # Table for projects (4 columns)
        self.projectTable = QtWidgets.QTableWidget()
        self.projectTable.setColumnCount(4)
        self.projectTable.setHorizontalHeaderLabels(["Projektname (ArtifactId)", "Name (GroupId)", "Java-Version", "Pfad"])
        self.projectTable.setSortingEnabled(True)
        self.projectTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.projectTable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        projects_layout.addWidget(self.projectTable)
        
        # Dropdown for maven-goals ("clean install", "clean", "test", "package")
        goalOptionsLayout = QtWidgets.QHBoxLayout()
        goalOptionsLabel = QtWidgets.QLabel("Maven Ziel:")
        self.goalComboBox = QtWidgets.QComboBox()
        goal_options_str = self.config.get("maven", "goal_options", fallback="clean install, clean, test")
        if goal_options_str:
            for goal in [g.strip() for g in goal_options_str.split(",") if g.strip()]:
                self.goalComboBox.addItem(goal)
        goalOptionsLayout.addWidget(goalOptionsLabel)
        goalOptionsLayout.addWidget(self.goalComboBox)
        projects_layout.addLayout(goalOptionsLayout)
        
        # dynamic generated cheboxes (from "checkbox_options" in config-file)
        optionsGroup = QtWidgets.QGroupBox("Maven Optionen")
        optionsGroupLayout = QtWidgets.QHBoxLayout()
        self.dynamicCheckboxes = []
        checkbox_options_str = self.config.get("maven", "checkbox_options", fallback="")
        if checkbox_options_str:
            for option in [opt.strip() for opt in checkbox_options_str.split(",") if opt.strip()]:
                chk = QtWidgets.QCheckBox(option)
                self.dynamicCheckboxes.append(chk)
                optionsGroupLayout.addWidget(chk)
        optionsGroup.setLayout(optionsGroupLayout)
        projects_layout.addWidget(optionsGroup)
        
        # Inputfield for further maven options
        additionalOptionsLayout = QtWidgets.QHBoxLayout()
        additionalOptionsLabel = QtWidgets.QLabel("Manuelle Maven Optionen:")
        self.optionsInput = QtWidgets.QLineEdit(self.config.get("maven", "user_options", fallback=""))
        additionalOptionsLayout.addWidget(additionalOptionsLabel)
        additionalOptionsLayout.addWidget(self.optionsInput)
        projects_layout.addLayout(additionalOptionsLayout)
        
        # Build-Button
        self.buildButton = QtWidgets.QPushButton("Projekt bauen")
        self.buildButton.setStyleSheet("background-color: #007d8f; color: #FFFFFF; font-weight: bold; font-size: 12px;")
        self.buildButton.clicked.connect(self._buildProject)
        projects_layout.addWidget(self.buildButton)
        
        # Cancel-Button
        self.cancelButton = QtWidgets.QPushButton("Build abbrechen")
        self.cancelButton.setStyleSheet("background-color: #ff8c73; color: #000000; font-weight: bold; font-size: 12px;")
        self.cancelButton.clicked.connect(self._cancelBuild)
        self.cancelButton.setVisible(True)
        projects_layout.addWidget(self.cancelButton)
        
        # Log (Console)
        self.outputLog = QtWidgets.QTextEdit()
        self.outputLog.setReadOnly(True)
        self.outputLog.setFixedHeight(200)
        projects_layout.addWidget(self.outputLog)
        
        # Button to clear the console
        self.clearConsoleButton = QtWidgets.QPushButton("Konsole leeren")
        self.clearConsoleButton.setStyleSheet("background-color: #ff8c73; color: #00000; font-weight: bold; font-size: 12px;")
        self.clearConsoleButton.clicked.connect(self._clearConsole)
        projects_layout.addWidget(self.clearConsoleButton)
        
        tab_widget.addTab(tab_projects, "Maven Projekte")
        
        # --- Tab 2: Java Installations ---
        tab_java = QtWidgets.QWidget()
        java_layout = QtWidgets.QVBoxLayout(tab_java)
        java_label = QtWidgets.QLabel("Installierte Java-Versionen (Installationsverzeichnis):")
        java_layout.addWidget(java_label)
        
        # Table for the Java-Installations (4 columns)
        self.javaTable = QtWidgets.QTableWidget()
        self.javaTable.setColumnCount(4)
        self.javaTable.setHorizontalHeaderLabels(["Name", "Version", "Pfad", "Java-Bin"])
        self.javaTable.setSortingEnabled(True)
        self.javaTable.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.javaTable.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        java_layout.addWidget(self.javaTable)
        
        self.refreshJavaButton = QtWidgets.QPushButton("Java Versionen aktualisieren")
        self.refreshJavaButton.setStyleSheet("background-color: #007d8f; color: #FFFFFF; font-weight: bold; font-size: 12px;")
        self.refreshJavaButton.clicked.connect(self._refreshJavaList)
        java_layout.addWidget(self.refreshJavaButton)
        
        tab_widget.addTab(tab_java, "Java Installationen")

        # --- Tab 3: Info-Tab ---
        tab_hinweise = QtWidgets.QWidget()
        hinweise_layout = QtWidgets.QVBoxLayout(tab_hinweise)

        self.hinweisTextBox = QtWidgets.QTextBrowser()
        self.hinweisTextBox.setOpenExternalLinks(True)
        
        html_content = """
        <style>
        p {
         font-size: 12px;
        }
        </style>
        <h2>Maven Build Manager</h2>
        <p>Der Maven Build Manager ist ein reines Freizeitprojekt von mir.</p>
        <p>Solltest du Fragen, Hinweise oder Anregungen haben oder weitere Information zum Projekt benötigen, bitte kontaktiere mich einfach über die GitHub-Projektseite.</p>
        <h2>ChangeLog</h2>
        <p>
          <b>0.16a</b><br/>
          - Texte und Infos überarbeitet<br/>
          - Projekt auf GitHub veröffentlicht
        </p>
        <p>
          <b>0.15a</b><br/>
          - Vollständig lauffähige Alpha-Version<br/>
          - Info Tab hinzugefügt
          - Beschreibungen aktualisiert
        </p>
        <p>
          <b>0.14a</b><br/>
          - Korrektur der Speicherung der gewählten Einstellunge damit auch nur diese Settings überschrieben werden<br/>
          - Dynamische Ausgabe der Projekte damit der Anwendungsstart nicht unnötig verzögert wird
        </p>
        <p>
          <b>0.13a</b><br/>
          - Änderunge der Farben der Buttons<br/>
          - Größerverhältnise der Anwendung sowie der Konsole angepasst<br/>
          - Button zum Abbrechen des Builds hinzugefügt<br/>
          - Anwendungssperre während des Builds hinzugefügt
        </p>
        <p>
          <b>0.12a</b><br/>
          - Speicherung der gewählten Einstellungen hinzugefügt, damit beim Starten der Anwendung vorgeblendet werden kann<br/>
        </p>
        <p>
          <b>0.11</b><br/>
          - Dynamische Ausgabe des Build-Outputs hinzugefügt damit nicht erst beim Build-Ende alles angezeigt wird<br/>
          - Abbrechen Button hinzugefügt um den laufenden Build zu beenden
        </p>
        <p>
          <b>0.10a</b><br/>
          - Tooltips für die Pfade der Projekte hinzugefügt falls der Platz des Feldes nicht ausreicht<br/>
          - Anpassung der Ergebnisse (Tabelle statt Liste)
        </p>
        <p>
          <b>0.9a</b><br/>
          - Anzeige der installierten Java-Versionen aktualisiert<br/>
        </p>
        <p>
          <b>0.8a</b><br/>
          - Rekursives Einlesen der Projekte und nicht nur auf Base-Path Ebene damit auch Unterprojekte erkannt werden. Hinweis: Es werden nur pom.xml berücksichtigt, die KEIN parent definiert haben!<br/>
        </p>
        <p>
          <b>0.7a</b><br/>
          - Weitere Informationen zum Projekt hinzugefügt<br/>
          - Weitere Informationen zu den installierten Java-Versionen hinzugefügt<br/>
        </p>
        <p>
          <b>0.6a</b><br/>
          - Fefhlerbehebungen
        </p>
        <p>
          <b>0.5a</b><br/>
          - Dynamische Checkbox-Optionen aus der Config-Datei<br/>
          - DropeDown Menu für die Maven-Goals<br/>
          - Kombination der Optionen
        </p>
        <p>
          <b>0.4a</b><br/>
          - Über eine Config-Datei ist es nun möglich Optionen für die Oberfläche sowie die Pfade der Projekte und installierten Java-Versionen festzulegen
        </p>
        <p>
          <b>0.3a</b><br/>
          - Fehlerbehebungen
        </p>
        <p>
          <b>0.2a</b><br/>
          - Anpassung der Maven-/Build-Befehle
        </p>
        <p>
          <b>0.1a</b><br/>
          - Erstellung des Projekts, erste Blaupause
        </p>
        """
        self.hinweisTextBox.setHtml(html_content)
        hinweise_layout.addWidget(self.hinweisTextBox)

        # Adding the new tab
        tab_widget.addTab(tab_hinweise, "Hinweise")
        
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addWidget(tab_widget)
        self.setLayout(main_layout)
        
        self._loadProjectsAsync()
        self._refreshJavaList()

        QtCore.QTimer.singleShot(0, self.set_interactive_mode)

    def set_interactive_mode(self):
        header = self.projectTable.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

    def _loadProjectsAsync(self):
        self.projectTable.setRowCount(0)
        self.projects = []
        base_dir = self.config.get("maven", "projects_directory", fallback=".")
        self.projectLoaderWorker = ProjectLoaderWorker(base_dir)
        self.projectLoaderWorker.project_found.connect(self._addProject)
        self.projectLoaderWorker.start()

    def _addProject(self, project):
        self.projects.append(project)
        row = self.projectTable.rowCount()
        self.projectTable.insertRow(row)
        # Column 0: ArtifactId with tooltip for the full path
        item_artifact = QtWidgets.QTableWidgetItem(project.artifactId)
        item_artifact.setData(QtCore.Qt.UserRole, project)
        self.projectTable.setItem(row, 0, item_artifact)
        # Column 1: GroupId
        item_group = QtWidgets.QTableWidgetItem(project.groupId)
        self.projectTable.setItem(row, 1, item_group)
        # Column 2: Java-Version
        item_version = QtWidgets.QTableWidgetItem(project.java_version)
        self.projectTable.setItem(row, 2, item_version)
        # Column 3: Path with tooltip for the full path
        item_path = QtWidgets.QTableWidgetItem(project.path)
        item_path.setToolTip(project.path)
        self.projectTable.setItem(row, 3, item_path)

    def _refreshJavaList(self):
        self.javaTable.setRowCount(0)
        java_dir = self.config.get("java", "install_directory", fallback="")
        if os.path.isdir(java_dir):
            for entry in os.listdir(java_dir):
                full_path = os.path.join(java_dir, entry)
                if os.path.isdir(full_path):
                    version_info = "Unbekannt"
                    release_file = os.path.join(full_path, "release")
                    if os.path.isfile(release_file):
                        try:
                            with open(release_file, "r", encoding="utf-8") as rf:
                                for line in rf:
                                    if line.startswith("JAVA_VERSION="):
                                        parts = line.strip().split("=", 1)
                                        if len(parts) == 2:
                                            version_info = parts[1].strip().strip('"')
                                        break
                        except Exception as e:
                            version_info = "Fehler beim Lesen"
                    bin_path = os.path.join(full_path, "bin", "java")
                    existenz = "Vorhanden" if (os.path.isfile(bin_path) or os.path.isfile(bin_path + ".exe")) else "Nicht gefunden"
                    row = self.javaTable.rowCount()
                    self.javaTable.insertRow(row)
                    item_name = QtWidgets.QTableWidgetItem(entry)
                    self.javaTable.setItem(row, 0, item_name)
                    item_version = QtWidgets.QTableWidgetItem(version_info)
                    self.javaTable.setItem(row, 1, item_version)
                    item_path = QtWidgets.QTableWidgetItem(full_path)
                    self.javaTable.setItem(row, 2, item_path)
                    item_bin = QtWidgets.QTableWidgetItem(existenz)
                    self.javaTable.setItem(row, 3, item_bin)
        else:
            self.outputLog.append(f"Java-Installationsverzeichnis '{java_dir}' existiert nicht.")

    def _buildProject(self):
        selected_rows = self.projectTable.selectionModel().selectedRows()
        if not selected_rows:
            self.outputLog.append("Kein Projekt ausgewählt.")
            return
        row = selected_rows[0].row()
        item = self.projectTable.item(row, 0)
        project = item.data(QtCore.Qt.UserRole)
        self.outputLog.append(f"Baue Projekt: {project.artifactId}")
        
        # While a build is running disable GUI-Parts
        self.buildButton.setEnabled(False)
        self.goalComboBox.setEnabled(False)
        self.optionsInput.setEnabled(False)
        for chk in self.dynamicCheckboxes:
            chk.setEnabled(False)
        self.projectTable.setEnabled(False)
        # Show Cancel-Button
        self.cancelButton.setVisible(True)
        self.cancelButton.setEnabled(True)
        
        if platform.system().lower() == "windows":
            maven_executable = self.config.get("maven", "maven_executable", fallback="mvn.cmd")
        else:
            maven_executable = "mvn"
        
        goal_str = self.goalComboBox.currentText().strip()
        if goal_str:
            command = [maven_executable] + goal_str.split()
        else:
            command = [maven_executable]
        
        default_config_options = self.config.get("maven", "default_options", fallback="").split()
        extra_config_options = self.config.get("maven", "extra_options", fallback="").split()
        options_from_checkboxes = []
        for chk in self.dynamicCheckboxes:
            if chk.isChecked():
                options_from_checkboxes.extend(chk.text().split())
        user_options = self.optionsInput.text().strip().split() if self.optionsInput.text().strip() else []
        
        command += default_config_options + options_from_checkboxes + user_options + extra_config_options
        self.outputLog.append("Ausführung: " + " ".join(command))
        
        self.worker = MavenBuildWorker(command, project.path)
        self.worker.build_output.connect(lambda text: self.outputLog.append(text))
        self.worker.finished.connect(self._buildFinished)
        self.worker.start()

    def _buildFinished(self):
        # Enable GUI
        self.buildButton.setEnabled(True)
        self.goalComboBox.setEnabled(True)
        self.optionsInput.setEnabled(True)
        for chk in self.dynamicCheckboxes:
            chk.setEnabled(True)
        self.projectTable.setEnabled(True)
        self.cancelButton.setVisible(True)

    def _cancelBuild(self):
        if self.worker:
            self.worker.cancel()
            self.cancelButton.setEnabled(False)

    def _clearConsole(self):
        self.outputLog.clear()

    def _loadLastState(self):
        # Load saved build options from config
        last_goal = self.config.get("maven", "last_selected_goal", fallback="")
        if last_goal:
            index = self.goalComboBox.findText(last_goal)
            if index != -1:
                self.goalComboBox.setCurrentIndex(index)
        last_checked = self.config.get("maven", "last_checked_options", fallback="")
        if last_checked:
            last_checked_list = [s.strip() for s in last_checked.split(",") if s.strip()]
            for chk in self.dynamicCheckboxes:
                if chk.text() in last_checked_list:
                    chk.setChecked(True)
        last_user_options = self.config.get("maven", "last_user_options", fallback="")
        if last_user_options:
            self.optionsInput.setText(last_user_options)

    def closeEvent(self, event):
        # Reload relevant keys from confog
        updates = {
            "last_selected_goal": self.goalComboBox.currentText(),
            "last_checked_options": ", ".join([chk.text() for chk in self.dynamicCheckboxes if chk.isChecked()]),
            "last_user_options": self.optionsInput.text()
        }
        config_file = "config.ini"
        try:
            update_config_file(config_file, "maven", updates)
        except Exception as e:
            print("Fehler beim Aktualisieren der Konfiguration:", e)
        event.accept()

def main():
    config = configparser.ConfigParser()
    config_file = "config.ini"
    if os.path.exists(config_file):
        config.read(config_file)
    
    app = QtWidgets.QApplication(sys.argv)
    window = MavenBuildGUI(config)
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
