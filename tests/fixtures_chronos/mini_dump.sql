-- Mini export MySQL SYNTHÉTIQUE de l'ancien Kairos (Chronos), pour tester
-- scripts/migrate_from_chronos.py jusqu'au chargement dans PostgreSQL
-- (audits données B1/I6/I7/I8 et QA I12, lot 10). Aucune donnée réelle :
-- seule la structure des tables reprend celle du vrai export.
-- Cas couverts : projet clos dont la fin précède le début, tâche dont
-- l'échéance précède le début, phase liée, Client chef de projet et
-- intervenant, chef de projet intervenant, heures sans personne.

CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `password` varchar(255) DEFAULT NULL,
  `role` varchar(255) NOT NULL DEFAULT 'intervenant ',
  `isSuperUser` tinyint(1) DEFAULT '0',
  `token` text,
  `active` tinyint(1) NOT NULL DEFAULT '0',
  `isBanned` tinyint(1) NOT NULL DEFAULT '0',
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `users` VALUES (1,'admin@exemple.tn',NULL,'superuser',1,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(2,'chef.a@exemple.tn',NULL,'Chef_projet',0,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(3,'chef.b@exemple.tn',NULL,'Chef_projet',0,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(4,'inter@exemple.tn',NULL,'intervenant',0,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(5,'client@exemple.tn',NULL,'client',0,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(6,'rh@exemple.tn',NULL,'ressource_humaine',0,NULL,1,0,'2024-01-01 08:00:00','2024-01-01 08:00:00');

CREATE TABLE `UserProfiles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) DEFAULT NULL,
  `lastName` varchar(255) DEFAULT NULL,
  `poste` varchar(255) DEFAULT NULL,
  `phone` varchar(255) DEFAULT NULL,
  `image` varchar(255) DEFAULT NULL,
  `userID` int NOT NULL,
  `address` varchar(255) DEFAULT NULL,
  `hireDate` varchar(255) DEFAULT NULL,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `UserProfiles` VALUES (1,'Admin','Alpha',NULL,NULL,NULL,1,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(2,'Chef','Alif',NULL,NULL,NULL,2,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(3,'Chef','Ba',NULL,NULL,NULL,3,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(4,'Inter','Ta',NULL,NULL,NULL,4,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(5,'Client','Tha',NULL,NULL,NULL,5,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00'),(6,'Rh','Jim',NULL,NULL,NULL,6,NULL,NULL,'2024-01-01 08:00:00','2024-01-01 08:00:00');

CREATE TABLE `phases` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(3) NOT NULL,
  `abbreviation` char(255) NOT NULL,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `phases` VALUES (1,'EXE','EXE','2024-01-01 08:00:00','2024-01-01 08:00:00');

CREATE TABLE `lots` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `lots` VALUES (1,'Gros Œuvre','2024-01-01 08:00:00','2024-01-01 08:00:00');

CREATE TABLE `projects` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(255) NOT NULL,
  `customId` varchar(255) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `startDate` datetime NOT NULL,
  `dueDate` datetime DEFAULT NULL,
  `priority` int DEFAULT NULL,
  `createdBy` int NOT NULL,
  `manager` int NOT NULL,
  `managerHours` float NOT NULL DEFAULT '0',
  `isCodeCustomized` tinyint(1) NOT NULL DEFAULT '0',
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `state` varchar(255) NOT NULL DEFAULT 'doing',
  `prevPhaseTmp` varchar(255) DEFAULT NULL,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  `phaseID` int DEFAULT NULL,
  `prevPhase` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `projects` VALUES (1,'C1','26001X_Tour','Tour','2025-01-01 00:00:00','2025-12-01 00:00:00',NULL,1,2,0,0,1,'doing',NULL,'2025-01-01 08:00:00','2025-01-02 08:00:00',1,NULL),(2,'C2','26002X_Ancien','Ancien','2025-03-01 00:00:00','2025-02-01 00:00:00',NULL,1,2,0,0,1,'done',NULL,'2025-03-01 08:00:00','2025-05-10 08:00:00',1,NULL),(3,'C3','26003X_Suite','Suite','2025-04-01 00:00:00','2025-06-01 00:00:00',NULL,1,3,0,0,1,'doing',NULL,'2025-04-01 08:00:00','2025-04-02 08:00:00',1,2),(4,'C4','26004X_Client','Client chef','2025-04-01 00:00:00',NULL,NULL,1,5,0,0,1,'doing',NULL,'2025-04-01 08:00:00','2025-04-01 08:00:00',1,NULL);

CREATE TABLE `projectLots` (
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  `projectID` int NOT NULL,
  `lotID` int NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `projectLots` VALUES ('2025-01-01 08:00:00','2025-01-01 08:00:00',1,1);

CREATE TABLE `tasks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `startDate` datetime NOT NULL,
  `dueDate` datetime NOT NULL,
  `blockedDate` datetime DEFAULT NULL,
  `doneDate` datetime DEFAULT NULL,
  `isVerified` tinyint(1) NOT NULL DEFAULT '0',
  `totalHours` float DEFAULT NULL,
  `state` varchar(255) NOT NULL DEFAULT 'doing',
  `meta` varchar(255) DEFAULT NULL,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `tasks` VALUES (1,'Plan','2025-02-01 00:00:00','2025-01-15 00:00:00',NULL,NULL,0,NULL,'doing','{\"projectID\":1}','2025-02-01 08:00:00','2025-02-01 08:00:00'),(2,'Note','2025-02-01 00:00:00','2025-03-01 00:00:00',NULL,NULL,0,NULL,'doing',NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00');

CREATE TABLE `intervenants` (
  `id` int NOT NULL AUTO_INCREMENT,
  `file` mediumtext,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  `intervenantID` int DEFAULT NULL,
  `projectID` int DEFAULT NULL,
  `taskID` int DEFAULT NULL,
  `nbHours` float NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `intervenants` VALUES (1,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',4,1,NULL,0),(2,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',3,1,NULL,0),(3,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',5,1,NULL,0),(4,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',4,1,2,0),(5,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',NULL,1,NULL,0),(6,NULL,'2025-02-01 08:00:00','2025-02-01 08:00:00',5,1,2,0);

CREATE TABLE `interventionHours` (
  `id` int NOT NULL AUTO_INCREMENT,
  `hours` float NOT NULL DEFAULT '0',
  `date` date NOT NULL DEFAULT '2025-03-13',
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  `interventionID` int DEFAULT NULL,
  `projectID` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `interventionHours` VALUES (1,8,'2025-02-03','2025-02-03 18:00:00','2025-02-03 18:00:00',1,1),(2,3.5,'2025-02-04','2025-02-04 18:00:00','2025-02-04 18:00:00',5,1),(3,2,'2025-02-05','2025-02-05 18:00:00','2025-02-05 18:00:00',NULL,3);

CREATE TABLE `requests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `description` text NOT NULL,
  `state` tinyint(1) NOT NULL DEFAULT '0',
  `file` mediumtext,
  `createdAt` datetime NOT NULL,
  `updatedAt` datetime NOT NULL,
  `projectID` int DEFAULT NULL,
  `creatorID` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
INSERT INTO `requests` VALUES (1,'Besoin des plans',0,NULL,'2025-02-06 08:00:00','2025-02-06 08:00:00',1,4);
