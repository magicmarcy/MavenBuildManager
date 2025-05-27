# Maven Build Manager
Dieses Projekt ist ein reines Hobby-Projekt von mir. Dieses Programm soll das bauen verschiedener Projekte via Maven vereinfachen. 

## Die config.ini
In dieser Konfigurationsdatei werden die benötigten Pfade und Optionen hinterlegt. 

| Option | Beschreibung |
|--------|--------------|
|```projects_directory```| Hier muss das Verzeichnis angegeben werden, in welchem die zu bauenden Projekte liegen. Bitte beachte, dass nur Projekte aufgenommen werden, die KEINEN parent-Eintrag in ihrer pomxml haben
|```maven_executable```| Vollständiger Pfad zu Maven Executable (mvn.cmd)  
|```checkbox_options```| Hier werden die Optionen aufgelistet, die auf der Oberfläche als Checkboxen sichtbar sind
|```goal_options```| Inhalte des DropDowns für die Maven-Goals
|```last_selected_goal```| Hier wird gespeichert, welches Goal zuletzt ausgewählt wurde
|```last_checked_options```| Hier wird gespeichert, welche Optionen zuletzt ausgewählt wurden
|```last_user_options```| Hier wird gespeichert, welche Custom-Optionen zuletzt eingetragen wurden
|```install_directory```| Hier muss der vollständige Pfad der Java-Installationen angegeben werden

## How to use?
Im Grunde ist das alles selbsterklärend: Die benötigten Optionen in der config.ini eintragen und das Script starten. Nun das entsprechende Projekt auswählen und "Build starten" klicken, fertig. Das Ergebnis des Builds wird auf der eingebauten Konsole angezeigt.

## Screenshots
Main View:
![Screenshot der Main View](https://raw.githubusercontent.com/magicmarcy/MavenBuildManager/refs/heads/main/img/main_view.png)

Installierte Java-Versionen:
![Ansicht der installierten Java-Versionen](https://raw.githubusercontent.com/magicmarcy/MavenBuildManager/refs/heads/main/img/java_versions.png)

## Probleme, Ideen, Anregungen
Solltest du Probleme mit der Anwendung haben oder weitere Ideen oder Anregungen, nutze bitte den [GitHub Workflow unter Issues](https://github.com/magicmarcy/MavenBuildManager/issues) dazu und erstelle einfach eine neue Issue. Hier ist genau der richtige Platz dafür.